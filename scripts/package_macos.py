#!/usr/bin/env python3
"""Build, bundle, sign, and archive the macOS host."""

from __future__ import annotations

import argparse
import hashlib
import os
import plistlib
import platform
import shutil
import stat
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

from webrtc_m150_notices import NOTICE_RELATIVE_PATH, validate_notice_bundle


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
HOST_ROOT = REPOSITORY_ROOT / "baseline" / "MacHost"
SOURCE_INFO_PLIST = HOST_ROOT / "Info.plist"
PRODUCT_NAME = "Vibe Screen"
ARTIFACT_NAME = "Vibe-Screen"
EXECUTABLE_NAME = PRODUCT_NAME
DEFAULT_SIGN_IDENTITY = "Vibe Screen Dev"
SIGN_IDENTITY_ENV = "VIBE_SCREEN_SIGN_IDENTITY"
WEBRTC_FRAMEWORK_NAME = "WebRTC.framework"
RESOURCE_BUNDLE_NAME = "Telemachus_Telemachus.bundle"
REPRODUCIBLE_TIMESTAMP = 315_532_800  # 1980-01-01, the ZIP timestamp floor.
SOURCE_COMMIT_PLIST_KEY = "VibeScreenSourceCommit"
SOURCE_TREE_PLIST_KEY = "VibeScreenSourceTree"
SOURCE_DIRTY_PLIST_KEY = "VibeScreenSourceDirty"
PREFLIGHT_EXTERNAL_COMMAND_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class SourceIdentity:
    commit: str
    tree: str
    dirty: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a versioned Vibe Screen macOS .app and ZIP archive."
    )
    parser.add_argument(
        "--version",
        help="Release version; defaults to CFBundleShortVersionString.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPOSITORY_ROOT / ".build" / "release-artifacts",
        help="Artifact directory (default: .build/release-artifacts).",
    )
    parser.add_argument(
        "--sign-identity",
        default=os.environ.get(SIGN_IDENTITY_ENV, DEFAULT_SIGN_IDENTITY),
        help=(
            "codesign identity; '-' produces a local ad-hoc signature. "
            f"Defaults to ${SIGN_IDENTITY_ENV} or the stable "
            f"'{DEFAULT_SIGN_IDENTITY}' "
            "self-signed identity so the signing hash (and thus macOS Screen "
            "Recording/Accessibility grants) stays stable across rebuilds. Pass "
            "'-' explicitly for an ad-hoc build on machines without that identity; "
            "any other missing identity fails fast instead of silently degrading."
        ),
    )
    return parser.parse_args()


def run(*command: str, cwd: Path | None = None, timeout: float | None = None) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    return completed.stdout.strip()


def command_text(command: tuple[str, ...] | list[str] | str) -> str:
    if isinstance(command, str):
        return command
    return " ".join(command)


def resolve_sign_identity(requested: str) -> str:
    """Return a usable codesign identity.

    The default identity ('Vibe Screen Dev') keeps the signing hash stable across
    local rebuilds so macOS Screen Recording/Accessibility grants survive. An
    ad-hoc signature (requested with '-') is only used when the operator passes
    it explicitly; any other missing identity fails fast so a local rebuild does
    not silently invalidate TCC grants. CI workflows must pass '--sign-identity -'
    explicitly to produce ad-hoc signed preview artifacts.
    """
    if requested == "-":
        return requested
    lookup_command = ("/usr/bin/security", "find-identity", "-v", "-p", "codesigning")
    try:
        lookup = subprocess.run(
            lookup_command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=PREFLIGHT_EXTERNAL_COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise SystemExit(
            f"security find-identity -v -p codesigning timed out after "
            f"{PREFLIGHT_EXTERNAL_COMMAND_TIMEOUT_SECONDS:g}s; refusing to assume "
            f"codesign identity '{requested}' is available. Unlock or repair the "
            "keychain, then rerun preflight."
        ) from error
    quoted_identity = f'"{requested}"'
    matching_identities = [
        line.strip()
        for line in lookup.stdout.splitlines()
        if line.strip().endswith(quoted_identity)
    ]
    if lookup.returncode == 0 and len(matching_identities) == 1:
        return requested
    if lookup.returncode == 0 and len(matching_identities) > 1:
        raise SystemExit(
            f"multiple codesign identities named '{requested}' were found in the keychain. "
            "Remove or rename duplicates so local builds keep one stable certificate "
            "leaf hash for macOS Screen Recording/Accessibility grants."
        )
    raise SystemExit(
        f"codesign identity '{requested}' not found in the keychain. "
        f"Create the '{DEFAULT_SIGN_IDENTITY}' self-signed identity (or set "
        f"${SIGN_IDENTITY_ENV} to an existing identity), or pass "
        "'--sign-identity -' for an ad-hoc build. Ad-hoc signing changes the "
        "code-signing hash on every rebuild and invalidates macOS Screen "
        "Recording/Accessibility grants."
    )


def collect_source_identity(repository_root: Path = REPOSITORY_ROOT) -> SourceIdentity:
    try:
        commit = run(
            "git",
            "rev-parse",
            "HEAD",
            cwd=repository_root,
            timeout=PREFLIGHT_EXTERNAL_COMMAND_TIMEOUT_SECONDS,
        )
        tree = run(
            "git",
            "rev-parse",
            "HEAD^{tree}",
            cwd=repository_root,
            timeout=PREFLIGHT_EXTERNAL_COMMAND_TIMEOUT_SECONDS,
        )
        status = run(
            "git",
            "status",
            "--porcelain",
            cwd=repository_root,
            timeout=PREFLIGHT_EXTERNAL_COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.CalledProcessError as error:
        output = (error.stdout or str(error)).strip()
        raise SystemExit(f"could not resolve git source identity for macOS Host package: {output}") from error
    except subprocess.TimeoutExpired as error:
        raise SystemExit(
            f"git source identity lookup timed out after "
            f"{PREFLIGHT_EXTERNAL_COMMAND_TIMEOUT_SECONDS:g}s while running "
            f"{command_text(error.cmd)}; refusing to treat the installed Host as "
            "current-source evidence."
        ) from error
    return SourceIdentity(commit=commit, tree=tree, dirty=bool(status.strip()))


def read_source_plist() -> dict[str, object]:
    with SOURCE_INFO_PLIST.open("rb") as plist_file:
        return plistlib.load(plist_file)


def bundled_plist(source_plist: dict[str, object], version: str, source_identity: SourceIdentity) -> dict[str, object]:
    result = dict(source_plist)
    result["CFBundleExecutable"] = EXECUTABLE_NAME
    result["CFBundleIconFile"] = "AppIcon"
    result["CFBundleVersion"] = version
    result["CFBundleShortVersionString"] = version
    result[SOURCE_COMMIT_PLIST_KEY] = source_identity.commit
    result[SOURCE_TREE_PLIST_KEY] = source_identity.tree
    result[SOURCE_DIRTY_PLIST_KEY] = source_identity.dirty
    return result


def safe_remove(path: Path, output_dir: Path) -> None:
    resolved = path.resolve()
    output_root = output_dir.resolve()
    if resolved.parent != output_root:
        raise ValueError(f"refusing to remove path outside output directory: {resolved}")
    if resolved.is_dir():
        shutil.rmtree(resolved)
    elif resolved.exists():
        resolved.unlink()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_mtimes(root: Path) -> None:
    """Remove wall-clock timestamps from the signed app before archiving."""
    paths = [root, *root.rglob("*")]
    for path in sorted(paths, key=lambda item: len(item.parts), reverse=True):
        os.utime(
            path,
            (REPRODUCIBLE_TIMESTAMP, REPRODUCIBLE_TIMESTAMP),
            follow_symlinks=False,
        )


def create_reproducible_zip(app_path: Path, archive_path: Path) -> None:
    entries = [app_path, *app_path.rglob("*")]
    with zipfile.ZipFile(
        archive_path,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path in sorted(entries, key=lambda item: item.relative_to(app_path.parent).as_posix()):
            relative = path.relative_to(app_path.parent).as_posix()
            mode = path.lstat().st_mode
            if path.is_dir() and not path.is_symlink():
                relative += "/"
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.flag_bits |= 0x800
            if path.is_symlink():
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, os.readlink(path).encode("utf-8"))
            elif path.is_dir():
                info.external_attr = (stat.S_IFDIR | stat.S_IMODE(mode)) << 16 | 0x10
                archive.writestr(info, b"")
            else:
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (stat.S_IFREG | stat.S_IMODE(mode)) << 16
                archive.writestr(info, path.read_bytes())


def main() -> int:
    args = parse_args()
    sign_identity = resolve_sign_identity(args.sign_identity)
    validate_notice_bundle(REPOSITORY_ROOT)
    source_identity = collect_source_identity(REPOSITORY_ROOT)
    source_plist = read_source_plist()
    version = args.version or str(source_plist["CFBundleShortVersionString"])
    if not version or any(character.isspace() for character in version):
        raise ValueError("version must be non-empty and contain no whitespace")

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    architecture = platform.machine()
    artifact_stem = f"{ARTIFACT_NAME}-macos-{version}-{architecture}"
    app_path = output_dir / f"{PRODUCT_NAME}.app"
    archive_path = output_dir / f"{artifact_stem}.zip"
    checksum_path = output_dir / f"{artifact_stem}.sha256"
    for path in (app_path, archive_path, checksum_path):
        safe_remove(path, output_dir)

    swift_path_map = f"{REPOSITORY_ROOT}=."
    build_command = (
        "swift",
        "build",
        "-c",
        "release",
        "-Xswiftc",
        "-file-prefix-map",
        "-Xswiftc",
        swift_path_map,
    )
    run(*build_command, cwd=HOST_ROOT)
    binary_dir = Path(
        run(*build_command, "--show-bin-path", cwd=HOST_ROOT)
    )
    executable = binary_dir / EXECUTABLE_NAME
    if not executable.is_file():
        raise FileNotFoundError(f"Swift build did not produce {executable}")

    contents = app_path / "Contents"
    macos_dir = contents / "MacOS"
    resources_dir = contents / "Resources"
    frameworks_dir = contents / "Frameworks"
    macos_dir.mkdir(parents=True)
    resources_dir.mkdir(parents=True)
    frameworks_dir.mkdir(parents=True)
    shutil.copy2(executable, macos_dir / EXECUTABLE_NAME)
    os.chmod(macos_dir / EXECUTABLE_NAME, 0o755)
    run("strip", "-S", str(macos_dir / EXECUTABLE_NAME))
    shutil.copy2(HOST_ROOT / "Resources" / "AppIcon.icns", resources_dir)
    shutil.copy2(HOST_ROOT / "Resources" / "Credits.html", resources_dir)
    shutil.copy2(REPOSITORY_ROOT / "baseline" / "LICENSE", resources_dir / "LICENSE.txt")
    shutil.copy2(REPOSITORY_ROOT / "baseline" / "NOTICE", resources_dir / "NOTICE.txt")
    web_rtc_framework = binary_dir / WEBRTC_FRAMEWORK_NAME
    resource_bundle = binary_dir / RESOURCE_BUNDLE_NAME
    if not web_rtc_framework.is_dir():
        raise FileNotFoundError(f"Swift build did not produce {web_rtc_framework}")
    if not resource_bundle.is_dir():
        raise FileNotFoundError(f"Swift build did not produce {resource_bundle}")
    shutil.copytree(
        web_rtc_framework,
        frameworks_dir / WEBRTC_FRAMEWORK_NAME,
        symlinks=True,
    )
    shutil.copytree(resource_bundle, resources_dir / RESOURCE_BUNDLE_NAME)
    packaged_notice = resources_dir / RESOURCE_BUNDLE_NAME / "ThirdParty" / NOTICE_RELATIVE_PATH.name
    if not packaged_notice.is_file():
        raise FileNotFoundError(f"Swift resource bundle omitted required notice: {packaged_notice}")

    with (contents / "Info.plist").open("wb") as plist_file:
        plistlib.dump(
            bundled_plist(source_plist, version, source_identity),
            plist_file,
            sort_keys=True,
        )

    run(
        "codesign",
        "--force",
        "--sign",
        sign_identity,
        str(frameworks_dir / WEBRTC_FRAMEWORK_NAME),
    )
    run(
        "codesign",
        "--force",
        "--sign",
        sign_identity,
        "--entitlements",
        str(HOST_ROOT / "Telemachus.entitlements"),
        str(app_path),
    )
    run("codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app_path))
    normalize_mtimes(app_path)
    create_reproducible_zip(app_path, archive_path)
    checksum_path.write_text(
        f"{sha256(archive_path)}  {archive_path.name}\n",
        encoding="utf-8",
    )
    print(app_path)
    print(archive_path)
    print(checksum_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
