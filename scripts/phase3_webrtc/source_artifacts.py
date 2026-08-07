"""Repository fingerprint and build artifact binding."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from scripts.phase3_webrtc.model import (
    BUILD_MANIFEST_NAME,
    BUILD_MANIFEST_SCHEMA,
    E2EFailure,
    EVIDENCE_SCHEMA,
    GENERATED_SOURCE_PATH_PREFIXES,
    SIGNALING_VERSION,
)
from scripts.phase3_webrtc.privacy import write_private_text
from scripts.phase3_webrtc.processes import run_checked, version_output


_ALLOWED_TRACKED_METADATA_SYMLINKS = {
    "AGENTS.md": "CLAUDE.md",
    "CLAUDE.md": "README.md",
}
_BUILD_INPUT_ROOTS = ("services/signaling", "baseline/MacHost")
_BUILD_OUTPUT_PREFIXES = (
    "baseline/MacHost/.build",
    "services/signaling/.build",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _descriptor_sha256(descriptor: int) -> str:
    digest = hashlib.sha256()
    os.lseek(descriptor, 0, os.SEEK_SET)
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
    os.lseek(descriptor, 0, os.SEEK_SET)
    return digest.hexdigest()


@dataclass
class VerifiedExecutable:
    source_path: Path
    sha256: str
    descriptor: int
    execution_path: Path
    execution_descriptor: int
    private_directory: Path | None = None
    private_directory_descriptor: int = -1
    environment_overrides: dict[str, str] | None = None
    runtime_artifacts: dict[str, str] | None = None

    @property
    def pass_fds(self) -> tuple[int, ...]:
        if self.private_directory is not None:
            return ()
        return (self.execution_descriptor,)

    @property
    def cwd(self) -> Path:
        return self.source_path.parent

    def validate_execution_target(self) -> None:
        descriptor_stat = os.fstat(self.execution_descriptor)
        if self.private_directory is None:
            if _descriptor_sha256(self.execution_descriptor) != self.sha256:
                raise E2EFailure("verified executable descriptor changed before execution")
            return
        try:
            path_stat = os.stat(self.execution_path, follow_symlinks=False)
        except OSError:
            raise E2EFailure("verified executable snapshot disappeared before execution") from None
        if not _same_inode(descriptor_stat, path_stat):
            raise E2EFailure("verified executable snapshot changed before execution")
        if _descriptor_sha256(self.execution_descriptor) != self.sha256:
            raise E2EFailure("verified executable snapshot hash changed before execution")
        if self.runtime_artifacts is not None:
            framework_root = self.execution_path.parent / "WebRTC.framework"
            framework = _read_webrtc_framework(framework_root, copy_root=None)
            if framework["sha256"] != self.runtime_artifacts["webrtc_framework_sha256"]:
                raise E2EFailure("verified WebRTC framework snapshot hash changed before execution")
            if framework["bundle_sha256"] != self.runtime_artifacts["webrtc_framework_bundle_sha256"]:
                raise E2EFailure("verified WebRTC framework snapshot layout changed before execution")

    def close(self) -> None:
        for descriptor in {self.descriptor, self.execution_descriptor}:
            if descriptor >= 0:
                os.close(descriptor)
        self.descriptor = -1
        self.execution_descriptor = -1
        if self.private_directory is not None:
            if self.private_directory_descriptor >= 0:
                os.close(self.private_directory_descriptor)
                self.private_directory_descriptor = -1
            shutil.rmtree(self.private_directory)


def _descriptor_execution_path(descriptor: int) -> Path | None:
    if platform.system() == "Linux" and Path("/proc/self/fd").is_dir():
        return Path("/proc/self/fd") / str(descriptor)
    return None


def _same_inode(before: os.stat_result, after: os.stat_result) -> bool:
    return (
        before.st_dev == after.st_dev
        and before.st_ino == after.st_ino
        and before.st_mode == after.st_mode
        and before.st_size == after.st_size
        and before.st_mtime_ns == after.st_mtime_ns
        and before.st_ctime_ns == after.st_ctime_ns
    )


_MACH_O_MAGICS = {
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
    b"\xca\xfe\xba\xbf",
    b"\xbf\xba\xfe\xca",
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xce",
    b"\xcf\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
}
_WEBRTC_FRAMEWORK_SYMLINKS = {
    "Versions/Current": "A",
    "WebRTC": "Versions/Current/WebRTC",
    "Resources": "Versions/Current/Resources",
}
_WEBRTC_FRAMEWORK_FILES = (
    "Versions/A/WebRTC",
    "Versions/A/Resources/Info.plist",
    "Versions/A/Resources/PrivacyInfo.xcprivacy",
)


def _read_file_descriptor(descriptor: int, label: str) -> tuple[bytes, os.stat_result]:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode):
        raise E2EFailure(f"{label} is not a regular file")
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
    after = os.fstat(descriptor)
    if not _same_inode(before, after):
        raise E2EFailure(f"{label} changed while it was being read")
    return b"".join(chunks), after


def _open_path_without_symlinks(root_fd: int, relative_path: str, label: str) -> int:
    components = relative_path.split("/")
    parent_fd = os.dup(root_fd)
    try:
        for component in components[:-1]:
            next_fd = _open_directory_at(parent_fd, component, label)
            os.close(parent_fd)
            parent_fd = next_fd
        return os.open(
            components[-1],
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_fd,
        )
    except OSError:
        raise E2EFailure(f"{label} path is unavailable or symlinked") from None
    finally:
        os.close(parent_fd)


def _write_snapshot_file(path: Path, content: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        mode,
    )
    try:
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_webrtc_framework(
    framework_root: Path,
    *,
    copy_root: Path | None,
) -> dict[str, str]:
    try:
        root_fd = os.open(
            framework_root,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError:
        raise E2EFailure("WebRTC framework is unavailable or symlinked") from None
    manifest_entries: list[dict[str, str]] = []
    try:
        root_before = os.fstat(root_fd)
        for relative_path in _WEBRTC_FRAMEWORK_FILES:
            descriptor = _open_path_without_symlinks(
                root_fd, relative_path, f"WebRTC framework {relative_path}"
            )
            try:
                content, descriptor_stat = _read_file_descriptor(
                    descriptor, f"WebRTC framework {relative_path}"
                )
                current = os.stat(
                    relative_path,
                    dir_fd=root_fd,
                    follow_symlinks=False,
                )
                if not _same_inode(descriptor_stat, current):
                    raise E2EFailure(
                        f"WebRTC framework {relative_path} changed while it was being read"
                    )
            finally:
                os.close(descriptor)
            if relative_path.endswith("/WebRTC") and content[:4] not in _MACH_O_MAGICS:
                raise E2EFailure("WebRTC framework executable is not a Mach-O binary")
            if not content:
                raise E2EFailure(f"WebRTC framework {relative_path} is empty")
            content_hash = hashlib.sha256(content).hexdigest()
            manifest_entries.append(
                {"path": relative_path, "type": "file", "sha256": content_hash}
            )
            if copy_root is not None:
                _write_snapshot_file(
                    copy_root / relative_path,
                    content,
                    0o700 if relative_path.endswith("/WebRTC") else 0o600,
                )
        for relative_path, expected_target in _WEBRTC_FRAMEWORK_SYMLINKS.items():
            path_stat = os.stat(relative_path, dir_fd=root_fd, follow_symlinks=False)
            if not stat.S_ISLNK(path_stat.st_mode):
                raise E2EFailure(f"WebRTC framework {relative_path} is not a symlink")
            target = os.readlink(relative_path, dir_fd=root_fd)
            if target != expected_target:
                raise E2EFailure(f"WebRTC framework {relative_path} has an invalid target")
            current_link = os.stat(
                relative_path, dir_fd=root_fd, follow_symlinks=False
            )
            if not _same_inode(path_stat, current_link):
                raise E2EFailure(
                    f"WebRTC framework {relative_path} changed while it was being read"
                )
            manifest_entries.append(
                {"path": relative_path, "type": "symlink", "target": target}
            )
            if copy_root is not None:
                destination = copy_root / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                os.symlink(target, destination)
        root_after = os.fstat(root_fd)
        current_root = os.stat(framework_root, follow_symlinks=False)
        if not _same_inode(root_before, root_after) or not _same_inode(root_after, current_root):
            raise E2EFailure("WebRTC framework changed while it was being read")
    except FileNotFoundError:
        raise E2EFailure("WebRTC framework runtime bundle is incomplete") from None
    finally:
        os.close(root_fd)
    manifest_entries.sort(key=lambda entry: entry["path"])
    bundle_hash = hashlib.sha256(
        json.dumps(manifest_entries, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    binary_hash = next(
        entry["sha256"]
        for entry in manifest_entries
        if entry["path"] == "Versions/A/WebRTC"
    )
    return {"sha256": binary_hash, "bundle_sha256": bundle_hash}


def webrtc_framework_manifest(repo_root: Path, mac_binary: Path) -> dict[str, str]:
    framework_root = mac_binary.parent / "WebRTC.framework"
    hashes = _read_webrtc_framework(framework_root, copy_root=None)
    return {
        "path": str(framework_root.relative_to(repo_root)),
        **hashes,
    }


def _open_directory_at(parent_fd: int, component: str, label: str) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        return os.open(component, flags, dir_fd=parent_fd)
    except OSError:
        raise E2EFailure(f"{label} path contains an unavailable or symlinked directory") from None


def _open_parent_directory(repo_fd: int, relative_path: str, label: str) -> tuple[int, str]:
    components = _source_path_components(relative_path)
    parent_fd = os.dup(repo_fd)
    try:
        for component in components[:-1]:
            next_fd = _open_directory_at(parent_fd, component, label)
            os.close(parent_fd)
            parent_fd = next_fd
        return parent_fd, components[-1]
    except Exception:
        os.close(parent_fd)
        raise


def _read_regular_file_at(repo_fd: int, relative_path: str, label: str) -> bytes:
    parent_fd, leaf = _open_parent_directory(repo_fd, relative_path, label)
    descriptor = -1
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(leaf, flags, dir_fd=parent_fd)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise E2EFailure(f"{label} is not a regular file: {relative_path}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        current = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        if not _same_inode(before, after) or not _same_inode(after, current):
            raise E2EFailure(f"{label} changed while it was being read: {relative_path}")
        return b"".join(chunks)
    except FileNotFoundError:
        raise E2EFailure(f"{label} disappeared: {relative_path}") from None
    except OSError:
        raise E2EFailure(f"{label} could not be read without following symlinks: {relative_path}") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(parent_fd)


def _read_symlink_at(repo_fd: int, relative_path: str, label: str) -> str:
    parent_fd, leaf = _open_parent_directory(repo_fd, relative_path, label)
    try:
        before = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISLNK(before.st_mode):
            raise E2EFailure(f"{label} is not a symlink: {relative_path}")
        target = os.readlink(leaf, dir_fd=parent_fd)
        after = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        if not _same_inode(before, after):
            raise E2EFailure(f"{label} changed while it was being read: {relative_path}")
        return target
    except FileNotFoundError:
        raise E2EFailure(f"{label} disappeared: {relative_path}") from None
    except OSError:
        raise E2EFailure(f"{label} could not be read safely: {relative_path}") from None
    finally:
        os.close(parent_fd)


def repository_revision(repo_root: Path) -> str:
    revision = version_output(["git", "rev-parse", "HEAD"], repo_root)
    if re.fullmatch(r"[0-9a-fA-F]{40,64}", revision) is None:
        raise E2EFailure(f"git returned an invalid HEAD revision: {revision!r}")
    return revision.lower()


def git_bytes(arguments: list[str], repo_root: Path) -> bytes:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        error_text = completed.stderr.decode("utf-8", errors="replace").strip()
        raise E2EFailure(f"git {' '.join(arguments)} failed: {error_text}")
    return completed.stdout


def tracked_entries(repo_root: Path) -> dict[str, dict[str, str]]:
    output = git_bytes(["ls-files", "--stage", "-z"], repo_root)
    entries: dict[str, dict[str, str]] = {}
    for raw_entry in output.split(b"\0"):
        if not raw_entry:
            continue
        try:
            raw_metadata, raw_path = raw_entry.split(b"\t", 1)
            fields = raw_metadata.split(b" ")
            raw_mode, raw_object, raw_stage = fields
        except ValueError:
            raise E2EFailure("git returned an invalid tracked source entry") from None
        relative_path = os.fsdecode(raw_path).replace(os.sep, "/")
        mode = raw_mode.decode("ascii", errors="strict")
        if raw_stage != b"0" or relative_path in entries:
            raise E2EFailure(f"tracked source has conflicting index stages: {relative_path}")
        entries[relative_path] = {
            "mode": mode,
            "object": raw_object.decode("ascii", errors="strict"),
        }
    return entries


def _source_path_components(relative_path: str) -> tuple[str, ...]:
    path = Path(relative_path)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise E2EFailure(f"git returned an invalid source path: {relative_path}")
    return path.parts


def _validate_allowed_metadata_symlink(
    repo_root: Path,
    path: Path,
    relative_path: str,
    tracked: dict[str, dict[str, str]],
) -> None:
    expected_target = _ALLOWED_TRACKED_METADATA_SYMLINKS[relative_path]
    try:
        actual_target = os.readlink(path)
    except OSError:
        raise E2EFailure(
            f"allowed metadata symlink is unavailable: {relative_path}"
        ) from None
    if actual_target != expected_target:
        raise E2EFailure(
            f"allowed metadata symlink target changed: {relative_path}"
        )
    try:
        resolved = path.resolve(strict=True)
        resolved_relative = resolved.relative_to(repo_root).as_posix()
    except (OSError, RuntimeError, ValueError):
        raise E2EFailure(
            f"allowed metadata symlink does not resolve inside the repository: {relative_path}"
        ) from None
    resolved_entry = tracked.get(resolved_relative)
    if not resolved_entry or resolved_entry["mode"] not in ("100644", "100755") or not resolved.is_file():
        raise E2EFailure(
            f"allowed metadata symlink must resolve to a tracked regular file: {relative_path}"
        )


def _validate_tracked_source_symlinks(
    repo_root: Path,
    tracked: dict[str, dict[str, str]],
) -> None:
    for relative_path, entry in tracked.items():
        mode = entry["mode"]
        if mode == "120000" and relative_path not in _ALLOWED_TRACKED_METADATA_SYMLINKS:
            raise E2EFailure(f"tracked source symlink is not allowed: {relative_path}")

    validated_metadata_symlinks: set[str] = set()
    for relative_path, entry in tracked.items():
        mode = entry["mode"]
        current = repo_root
        components = _source_path_components(relative_path)
        for index, component in enumerate(components):
            current /= component
            try:
                current_mode = current.lstat().st_mode
            except FileNotFoundError:
                if mode == "120000":
                    raise E2EFailure(
                        f"tracked metadata symlink is missing: {relative_path}"
                    ) from None
                break
            except OSError:
                raise E2EFailure(
                    f"tracked source path could not be inspected: {relative_path}"
                ) from None
            if not stat.S_ISLNK(current_mode):
                continue
            symlink_path = Path(*components[: index + 1]).as_posix()
            is_leaf = index == len(components) - 1
            if (
                not is_leaf
                or symlink_path not in _ALLOWED_TRACKED_METADATA_SYMLINKS
                or tracked.get(symlink_path, {}).get("mode") != "120000"
            ):
                raise E2EFailure(
                    f"tracked source path contains an untrusted symlink: {symlink_path}"
                )
            _validate_allowed_metadata_symlink(
                repo_root,
                current,
                symlink_path,
                tracked,
            )
            validated_metadata_symlinks.add(symlink_path)
            break

    expected_metadata_symlinks = {
        path
        for path, entry in tracked.items()
        if entry["mode"] == "120000" and path in _ALLOWED_TRACKED_METADATA_SYMLINKS
    }
    missing = sorted(expected_metadata_symlinks - validated_metadata_symlinks)
    if missing:
        raise E2EFailure(
            "tracked metadata symlinks were not safely materialized: "
            + ",".join(missing)
        )


def _reject_untracked_source_symlink(repo_root: Path, relative_path: str) -> None:
    current = repo_root
    components = _source_path_components(relative_path)
    for index, component in enumerate(components):
        current /= component
        try:
            current_mode = current.lstat().st_mode
        except FileNotFoundError:
            return
        except OSError:
            raise E2EFailure(
                f"untracked source path could not be inspected: {relative_path}"
            ) from None
        if stat.S_ISLNK(current_mode):
            symlink_path = Path(*components[: index + 1]).as_posix()
            raise E2EFailure(
                f"untracked source path contains a symlink: {symlink_path}"
            )


def _reject_tracked_runtime_pass_evidence(
    repo_root: Path,
    tracked: dict[str, dict[str, str]],
) -> None:
    for relative_path, entry in tracked.items():
        mode = entry["mode"]
        if mode not in ("100644", "100755") or not relative_path.endswith(".json"):
            continue
        path = repo_root / relative_path
        if not path.is_file():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if (
            isinstance(value, dict)
            and value.get("schema") == EVIDENCE_SCHEMA
            and value.get("result") == "pass"
        ):
            raise E2EFailure(
                "tracked Phase 3 runtime PASS evidence is forbidden; "
                f"write it under .build instead: {relative_path}"
            )


def _reject_untracked_runtime_pass_evidence(path: Path, relative_path: str) -> None:
    if not relative_path.endswith(".json"):
        return
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return
    if (
        isinstance(value, dict)
        and value.get("schema") == EVIDENCE_SCHEMA
        and value.get("result") == "pass"
    ):
        raise E2EFailure(
            "untracked Phase 3 runtime PASS evidence must be stored under .build: "
            f"{relative_path}"
        )


def _reject_runtime_pass_content(content: bytes, relative_path: str, kind: str) -> None:
    if not relative_path.endswith(".json"):
        return
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return
    if (
        isinstance(value, dict)
        and value.get("schema") == EVIDENCE_SCHEMA
        and value.get("result") == "pass"
    ):
        location = "write it under .build instead" if kind == "tracked" else "must be stored under .build"
        raise E2EFailure(
            f"{kind} Phase 3 runtime PASS evidence is forbidden; {location}: {relative_path}"
        )


def bytes_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def canonical_json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return bytes_sha256(encoded)


def _index_content(repo_root: Path, object_id: str) -> bytes:
    return git_bytes(["cat-file", "blob", object_id], repo_root)


def _is_build_output(relative_path: str) -> bool:
    return any(
        relative_path == prefix
        or relative_path.startswith(prefix + "/")
        or relative_path.startswith(prefix + "-")
        for prefix in _BUILD_OUTPUT_PREFIXES
    )


def _ignored_build_inputs(repo_root: Path) -> list[str]:
    output = git_bytes(
        [
            "ls-files",
            "--others",
            "--ignored",
            "--exclude-standard",
            "-z",
            "--",
            *_BUILD_INPUT_ROOTS,
        ],
        repo_root,
    )
    return sorted(
        normalized
        for raw_path in output.split(b"\0")
        if raw_path
        for normalized in (os.fsdecode(raw_path).replace(os.sep, "/"),)
        if not _is_build_output(normalized)
    )


def repository_source_state(repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    revision = repository_revision(repo_root)
    tracked = tracked_entries(repo_root)
    _validate_tracked_source_symlinks(repo_root, tracked)
    ignored_build_inputs = _ignored_build_inputs(repo_root)
    if ignored_build_inputs:
        raise E2EFailure(
            "ignored files exist under a Phase 3 build input root; "
            "move them to an explicit build output directory or remove them"
        )
    repo_fd = os.open(repo_root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    tracked_manifest: list[dict[str, str]] = []
    tracked_dirty = False
    try:
        for relative_path, entry in sorted(tracked.items()):
            mode = entry["mode"]
            try:
                if mode in ("100644", "100755"):
                    content = _read_regular_file_at(repo_fd, relative_path, "tracked source")
                elif mode == "120000":
                    symlink_target = _read_symlink_at(
                        repo_fd, relative_path, "tracked metadata symlink"
                    )
                    if symlink_target != _ALLOWED_TRACKED_METADATA_SYMLINKS.get(
                        relative_path
                    ):
                        raise E2EFailure(
                            f"allowed metadata symlink target changed: {relative_path}"
                        )
                    content = symlink_target.encode(
                        "utf-8", errors="surrogateescape"
                    )
                else:
                    raise E2EFailure(f"tracked source has unsupported mode: {relative_path}")
            except E2EFailure as exception:
                if " disappeared:" not in str(exception):
                    raise
                tracked_manifest.append(
                    {"path": relative_path, "mode": mode, "state": "missing"}
                )
                tracked_dirty = True
                continue
            _reject_runtime_pass_content(content, relative_path, "tracked")
            tracked_manifest.append(
                {
                    "path": relative_path,
                    "mode": mode,
                    "state": "present",
                    "sha256": bytes_sha256(content),
                }
            )
            if content != _index_content(repo_root, entry["object"]):
                tracked_dirty = True
    finally:
        os.close(repo_fd)
    untracked_output = git_bytes(
        ["ls-files", "--others", "--exclude-standard", "-z"], repo_root
    )
    untracked_paths = sorted(
        os.fsdecode(raw_path)
        for raw_path in untracked_output.split(b"\0")
        if raw_path
    )
    untracked_manifest = []
    for relative_path in untracked_paths:
        normalized_path = relative_path.replace(os.sep, "/")
        if any(normalized_path.startswith(prefix) for prefix in GENERATED_SOURCE_PATH_PREFIXES):
            continue
        _reject_untracked_source_symlink(repo_root, relative_path)
        path = repo_root / relative_path
        if path.is_file():
            repo_fd = os.open(repo_root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                content = _read_regular_file_at(repo_fd, normalized_path, "untracked source")
            finally:
                os.close(repo_fd)
            _reject_runtime_pass_content(content, normalized_path, "untracked")
            content_hash = bytes_sha256(content)
        else:
            raise E2EFailure(f"untracked source disappeared or is not a file: {relative_path}")
        untracked_manifest.append({"path": normalized_path, "sha256": content_hash})
    tracked_worktree_sha256 = canonical_json_sha256(tracked_manifest)
    untracked_manifest_sha256 = canonical_json_sha256(untracked_manifest)
    dirty = bool(tracked_dirty or untracked_manifest)
    fingerprint_inputs = {
        "repository_commit": revision,
        "tracked_worktree_sha256": tracked_worktree_sha256,
        "untracked_manifest_sha256": untracked_manifest_sha256,
        "ignored_build_inputs_sha256": canonical_json_sha256([]),
    }
    return {
        **fingerprint_inputs,
        "tracked_diff_sha256": tracked_worktree_sha256,
        "dirty": dirty,
        "evidence_qualification": (
            "non-commit evidence (dirty worktree)" if dirty else "commit evidence"
        ),
        "untracked_manifest": untracked_manifest,
        "source_fingerprint": canonical_json_sha256(fingerprint_inputs),
    }


def build_manifest_path(repo_root: Path) -> Path:
    return repo_root / "scripts/phase3_webrtc/.build" / BUILD_MANIFEST_NAME


def create_build_manifest(
    repo_root: Path,
    signaling_binary: Path,
    mac_binary: Path,
    source_state: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema": BUILD_MANIFEST_SCHEMA,
        "source_fingerprint": source_state["source_fingerprint"],
        "artifacts": {
            "signaling": {
                "path": str(signaling_binary.relative_to(repo_root)),
                "sha256": sha256(signaling_binary),
            },
            "mac_host": {
                "path": str(mac_binary.relative_to(repo_root)),
                "sha256": sha256(mac_binary),
            },
            "mac_webrtc_framework": webrtc_framework_manifest(
                repo_root, mac_binary
            ),
        },
        "runtime_artifacts": {
            "direct": {"turnserver_sha256": "not_used"},
            "relay": {"turnserver_sha256": "not_recorded"},
        },
    }


def repository_artifact_path(repo_root: Path, configured_path: Path, label: str) -> Path:
    repo_root = repo_root.resolve()
    candidate = configured_path if configured_path.is_absolute() else repo_root / configured_path
    resolved = candidate.resolve()
    try:
        resolved.relative_to(repo_root)
    except ValueError as exception:
        raise E2EFailure(f"{label} must be inside the repository: {configured_path}") from exception
    if not resolved.is_file():
        raise E2EFailure(f"{label} is missing: {resolved}")
    return resolved


def write_build_manifest(repo_root: Path, manifest: dict[str, Any]) -> None:
    write_private_text(
        build_manifest_path(repo_root),
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    )


def _read_build_manifest(repo_root: Path) -> dict[str, Any]:
    path = build_manifest_path(repo_root)
    if not path.is_file():
        raise E2EFailure("build manifest is missing; rebuild without --skip-build")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exception:
        raise E2EFailure(f"invalid build manifest: {exception}") from exception
    if manifest.get("schema") != BUILD_MANIFEST_SCHEMA:
        raise E2EFailure("build manifest has an unsupported schema")
    return manifest


def _validated_runtime_artifacts(manifest: dict[str, Any]) -> dict[str, Any]:
    runtime_artifacts = manifest.get("runtime_artifacts")
    if not isinstance(runtime_artifacts, dict):
        raise E2EFailure("build manifest omits runtime artifact bindings")
    direct = runtime_artifacts.get("direct")
    relay = runtime_artifacts.get("relay")
    if direct != {"turnserver_sha256": "not_used"}:
        raise E2EFailure("build manifest direct runtime artifacts are invalid")
    if not isinstance(relay, dict) or set(relay) != {"turnserver_sha256"}:
        raise E2EFailure("build manifest relay runtime artifacts are invalid")
    relay_hash = relay["turnserver_sha256"]
    if relay_hash != "not_recorded" and (
        not isinstance(relay_hash, str)
        or re.fullmatch(r"[0-9a-f]{64}", relay_hash) is None
    ):
        raise E2EFailure("build manifest relay turnserver hash is invalid")
    return runtime_artifacts


def record_turnserver_execution(repo_root: Path, executable_hash: str) -> None:
    if re.fullmatch(r"[0-9a-f]{64}", executable_hash) is None:
        raise E2EFailure("turnserver execution hash is invalid")
    _, _, _, manifest = verify_build_manifest(repo_root)
    runtime_artifacts = _validated_runtime_artifacts(manifest)
    runtime_artifacts["relay"] = {"turnserver_sha256": executable_hash}
    write_build_manifest(repo_root, manifest)


def _open_verified_executable(
    path: Path,
    descriptor: int,
    expected_hash: str,
    label: str,
) -> VerifiedExecutable:
    execution_descriptor = -1
    snapshot_write_descriptor = -1
    private_directory: Path | None = None
    private_directory_descriptor = -1
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise E2EFailure(f"{label} is not a regular file")
        actual_hash = _descriptor_sha256(descriptor)
        after = os.fstat(descriptor)
        if not _same_inode(before, after):
            raise E2EFailure(f"{label} changed while it was being verified")
        if actual_hash != expected_hash:
            raise E2EFailure(f"{label} hash does not match its build manifest")

        execution_path = _descriptor_execution_path(descriptor)
        if execution_path is not None:
            execution_descriptor = descriptor
        else:
            private_directory = Path(
                tempfile.mkdtemp(prefix="vibe-phase3-verified-exec-")
            )
            private_directory.chmod(0o700)
            private_directory_descriptor = os.open(
                private_directory,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
            )
            snapshot_name = "executable"
            snapshot_write_descriptor = os.open(
                snapshot_name,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o700,
                dir_fd=private_directory_descriptor,
            )
            os.fchmod(snapshot_write_descriptor, 0o700)
            os.lseek(descriptor, 0, os.SEEK_SET)
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                view = memoryview(chunk)
                while view:
                    written = os.write(snapshot_write_descriptor, view)
                    view = view[written:]
            os.fsync(snapshot_write_descriptor)
            written_stat = os.fstat(snapshot_write_descriptor)
            os.fsync(private_directory_descriptor)
            os.close(snapshot_write_descriptor)
            snapshot_write_descriptor = -1
            execution_descriptor = os.open(
                snapshot_name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=private_directory_descriptor,
            )
            reopened_stat = os.fstat(execution_descriptor)
            current_stat = os.stat(
                snapshot_name,
                dir_fd=private_directory_descriptor,
                follow_symlinks=False,
            )
            if not _same_inode(written_stat, reopened_stat) or not _same_inode(
                reopened_stat, current_stat
            ):
                raise E2EFailure(f"{label} private execution snapshot changed after write")
            if _descriptor_sha256(execution_descriptor) != expected_hash:
                raise E2EFailure(f"{label} private execution snapshot hash mismatch")
            execution_path = private_directory / snapshot_name

        verified = VerifiedExecutable(
            source_path=path,
            sha256=actual_hash,
            descriptor=descriptor,
            execution_path=execution_path,
            execution_descriptor=execution_descriptor,
            private_directory=private_directory,
            private_directory_descriptor=private_directory_descriptor,
        )
        verified.validate_execution_target()
        return verified
    except Exception:
        if snapshot_write_descriptor >= 0:
            os.close(snapshot_write_descriptor)
        if execution_descriptor >= 0 and execution_descriptor != descriptor:
            os.close(execution_descriptor)
        os.close(descriptor)
        if private_directory is not None:
            try:
                if private_directory_descriptor >= 0:
                    try:
                        os.unlink("executable", dir_fd=private_directory_descriptor)
                    except FileNotFoundError:
                        pass
                    os.close(private_directory_descriptor)
                private_directory.rmdir()
            except OSError:
                pass
        raise


def _attach_verified_webrtc_framework(
    executable: VerifiedExecutable,
    artifact: dict[str, Any],
    repo_root: Path,
) -> None:
    relative_path = artifact.get("path")
    expected_hash = artifact.get("sha256")
    expected_bundle_hash = artifact.get("bundle_sha256")
    if not isinstance(relative_path, str) or not relative_path:
        raise E2EFailure("build manifest WebRTC framework artifact has an invalid path")
    if not isinstance(expected_hash, str) or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None:
        raise E2EFailure("build manifest WebRTC framework artifact has an invalid hash")
    if not isinstance(expected_bundle_hash, str) or re.fullmatch(r"[0-9a-f]{64}", expected_bundle_hash) is None:
        raise E2EFailure("build manifest WebRTC framework artifact has an invalid bundle hash")
    framework_root = (repo_root / relative_path).resolve()
    try:
        framework_root.relative_to(repo_root.resolve())
    except ValueError as exception:
        raise E2EFailure("WebRTC framework must be inside the repository") from exception
    if framework_root != executable.source_path.parent / "WebRTC.framework":
        raise E2EFailure("WebRTC framework is not adjacent to the MacHost binary")
    if executable.private_directory is None:
        raise E2EFailure("MacHost execution requires a private runtime snapshot")
    snapshot_root = executable.private_directory / "WebRTC.framework"
    hashes = _read_webrtc_framework(framework_root, copy_root=snapshot_root)
    if hashes["sha256"] != expected_hash:
        raise E2EFailure("WebRTC framework hash does not match its build manifest")
    if hashes["bundle_sha256"] != expected_bundle_hash:
        raise E2EFailure("WebRTC framework layout does not match its build manifest")
    snapshot_hashes = _read_webrtc_framework(snapshot_root, copy_root=None)
    if snapshot_hashes != hashes:
        raise E2EFailure("WebRTC framework private snapshot hash mismatch")
    executable.runtime_artifacts = {
        "webrtc_framework_sha256": expected_hash,
        "webrtc_framework_bundle_sha256": expected_bundle_hash,
    }
    executable.environment_overrides = {
        "DYLD_FRAMEWORK_PATH": str(executable.private_directory)
    }
    executable.validate_execution_target()


@contextmanager
def open_verified_external_executable(
    configured_path: Path,
    label: str,
) -> Iterator[VerifiedExecutable]:
    try:
        path = configured_path.resolve(strict=True)
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError:
        raise E2EFailure(f"{label} is unavailable") from None
    snapshot: VerifiedExecutable | None = None
    try:
        descriptor_stat = os.fstat(descriptor)
        current = os.stat(path, follow_symlinks=False)
        if not _same_inode(descriptor_stat, current):
            raise E2EFailure(f"{label} changed while it was being opened")
        if not stat.S_ISREG(descriptor_stat.st_mode) or not descriptor_stat.st_mode & 0o111:
            raise E2EFailure(f"{label} is not an executable regular file")
        expected_hash = _descriptor_sha256(descriptor)
        snapshot = _open_verified_executable(path, descriptor, expected_hash, label)
        descriptor = -1
        yield snapshot
    finally:
        if snapshot is not None:
            snapshot.close()
        elif descriptor >= 0:
            os.close(descriptor)


def _open_repository_executable(
    repo_root: Path,
    relative_path: str,
    label: str,
) -> tuple[Path, int]:
    repo_root = repo_root.resolve()
    repo_descriptor = os.open(
        repo_root,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    parent_descriptor = -1
    try:
        parent_descriptor, leaf = _open_parent_directory(
            repo_descriptor, relative_path, label
        )
        descriptor = os.open(
            leaf,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_descriptor,
        )
        return repo_root / relative_path, descriptor
    except OSError:
        raise E2EFailure(
            f"{label} could not be opened without following symlinks"
        ) from None
    finally:
        if parent_descriptor >= 0:
            os.close(parent_descriptor)
        os.close(repo_descriptor)


@contextmanager
def open_verified_binaries(
    repo_root: Path,
    expected_signaling: Path | None = None,
    expected_mac_host: Path | None = None,
) -> Iterator[tuple[VerifiedExecutable, VerifiedExecutable, dict[str, Any]]]:
    manifest = _read_build_manifest(repo_root)
    source_state = repository_source_state(repo_root)
    if manifest.get("source_fingerprint") != source_state["source_fingerprint"]:
        raise E2EFailure("runtime source fingerprint no longer matches the build manifest")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise E2EFailure("build manifest omits artifact hashes")
    _validated_runtime_artifacts(manifest)
    opened: list[VerifiedExecutable] = []
    try:
        verified: dict[str, VerifiedExecutable] = {}
        expected = {"signaling": expected_signaling, "mac_host": expected_mac_host}
        for name in ("signaling", "mac_host"):
            artifact = artifacts.get(name)
            if not isinstance(artifact, dict):
                raise E2EFailure(f"build manifest omits the {name} artifact")
            relative_path = artifact.get("path")
            expected_hash = artifact.get("sha256")
            if not isinstance(relative_path, str) or not relative_path:
                raise E2EFailure(f"build manifest {name} artifact has an invalid path")
            if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
                raise E2EFailure(f"build manifest {name} artifact has an invalid hash")
            binary = repository_artifact_path(repo_root, Path(relative_path), f"{name} binary")
            if expected[name] is not None and binary != expected[name].resolve():
                raise E2EFailure(f"runtime {name} binary differs from the build manifest path")
            resolved_relative_path = binary.relative_to(repo_root.resolve()).as_posix()
            source_path, descriptor = _open_repository_executable(
                repo_root, resolved_relative_path, f"{name} binary"
            )
            snapshot = _open_verified_executable(
                source_path, descriptor, expected_hash, f"{name} binary"
            )
            opened.append(snapshot)
            verified[name] = snapshot
        framework_artifact = artifacts.get("mac_webrtc_framework")
        if not isinstance(framework_artifact, dict):
            raise E2EFailure("build manifest omits the mac_webrtc_framework artifact")
        _attach_verified_webrtc_framework(
            verified["mac_host"], framework_artifact, repo_root
        )
        yield verified["signaling"], verified["mac_host"], source_state
    finally:
        for executable in reversed(opened):
            executable.close()


def verify_build_manifest(
    repo_root: Path,
    expected_signaling: Path | None = None,
    expected_mac_host: Path | None = None,
) -> tuple[Path, Path, dict[str, Any], dict[str, Any]]:
    manifest = _read_build_manifest(repo_root)
    source_state = repository_source_state(repo_root)
    if manifest.get("source_fingerprint") != source_state["source_fingerprint"]:
        raise E2EFailure(
            "runtime source fingerprint no longer matches the build manifest"
        )
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise E2EFailure("build manifest omits artifact hashes")
    _validated_runtime_artifacts(manifest)
    resolved: dict[str, Path] = {}
    for name in ("signaling", "mac_host"):
        artifact = artifacts.get(name)
        if not isinstance(artifact, dict):
            raise E2EFailure(f"build manifest omits the {name} artifact")
        relative_path = artifact.get("path")
        if not isinstance(relative_path, str) or not relative_path:
            raise E2EFailure(f"build manifest {name} artifact has an invalid path")
        binary = repository_artifact_path(repo_root, Path(relative_path), f"{name} binary")
        if artifact.get("sha256") != sha256(binary):
            raise E2EFailure(f"{name} binary hash does not match its build manifest")
        resolved[name] = binary
    framework_artifact = artifacts.get("mac_webrtc_framework")
    if not isinstance(framework_artifact, dict):
        raise E2EFailure("build manifest omits the mac_webrtc_framework artifact")
    actual_framework = webrtc_framework_manifest(repo_root, resolved["mac_host"])
    if framework_artifact != actual_framework:
        raise E2EFailure("WebRTC framework does not match its build manifest")
    expected = {"signaling": expected_signaling, "mac_host": expected_mac_host}
    for name, path in expected.items():
        if path is not None and resolved[name] != path.resolve():
            raise E2EFailure(f"runtime {name} binary differs from the build manifest path")
    return resolved["signaling"], resolved["mac_host"], source_state, manifest


def build_binaries(repo_root: Path, timeout: int) -> tuple[Path, Path, list[str]]:
    source_state = repository_source_state(repo_root)
    signaling_root = repo_root / "services/signaling"
    mac_root = repo_root / "baseline/MacHost"
    signaling_binary = repo_root / "scripts/phase3_webrtc/.build/signaling/vibe-signaling"
    mac_binary = mac_root / ".build/release/Telemachus"
    signaling_binary.parent.mkdir(parents=True, exist_ok=True)
    outputs = [
        run_checked(
            [
                "go", "build", "-trimpath", "-ldflags", f"-X main.version={SIGNALING_VERSION}",
                "-o", str(signaling_binary), "./cmd/vibe-signaling",
            ],
            cwd=signaling_root,
            timeout=timeout,
        ).stdout,
        run_checked(
            ["swift", "build", "-c", "release"],
            cwd=mac_root,
            timeout=max(timeout, 300),
        ).stdout,
    ]
    mac_binary = repository_artifact_path(repo_root, mac_binary, "release MacHost binary")
    completed_source_state = repository_source_state(repo_root)
    if completed_source_state["source_fingerprint"] != source_state["source_fingerprint"]:
        raise E2EFailure("repository sources changed while binaries were building")
    write_build_manifest(
        repo_root,
        create_build_manifest(repo_root, signaling_binary, mac_binary, source_state),
    )
    verify_build_manifest(repo_root, signaling_binary, mac_binary)
    return signaling_binary, mac_binary, outputs


def locate_binaries(repo_root: Path) -> tuple[Path, Path]:
    signaling, mac_host, _, _ = verify_build_manifest(repo_root)
    return signaling, mac_host


def assert_evidence_matches_current_build(
    repo_root: Path,
    evidence: dict[str, Any],
) -> None:
    signaling, mac_host, source_state, manifest = verify_build_manifest(repo_root)
    evidence_source = evidence.get("environment", {}).get("repository_source", {})
    if evidence_source.get("source_fingerprint") != source_state["source_fingerprint"]:
        raise E2EFailure("evidence source fingerprint changed before evidence write")
    expected_hashes = {
        "signaling_sha256": sha256(signaling),
        "mac_host_sha256": sha256(mac_host),
        "webrtc_framework_sha256": manifest["artifacts"]["mac_webrtc_framework"]["sha256"],
    }
    actual_hashes = evidence.get("artifacts")
    if not isinstance(actual_hashes, dict):
        raise E2EFailure("evidence artifact hashes changed before evidence write")
    for name, expected_hash in expected_hashes.items():
        if actual_hashes.get(name) != expected_hash:
            raise E2EFailure("evidence artifact hashes changed before evidence write")
    turnserver_hash = actual_hashes.get("turnserver_sha256")
    if turnserver_hash != "not_used" and (
        not isinstance(turnserver_hash, str)
        or re.fullmatch(r"[0-9a-f]{64}", turnserver_hash) is None
    ):
        raise E2EFailure("evidence artifact hashes changed before evidence write")
    mode = evidence.get("mode")
    runtime_artifacts = _validated_runtime_artifacts(manifest)
    if mode not in {"direct", "relay"}:
        raise E2EFailure("evidence mode is invalid before evidence write")
    expected_turnserver_hash = runtime_artifacts[mode]["turnserver_sha256"]
    if turnserver_hash != expected_turnserver_hash:
        raise E2EFailure("evidence runtime artifact hash changed before evidence write")
