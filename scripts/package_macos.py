#!/usr/bin/env python3
"""Build, bundle, sign, and archive the macOS host."""

from __future__ import annotations

import argparse
import hashlib
import os
import plistlib
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
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
EXPECTED_SIGNING_LEAF_SHA1 = "9AAE572BF6D764E3436A6109197D345B5A87998C"
CODESIGN = "/usr/bin/codesign"
WEBRTC_FRAMEWORK_NAME = "WebRTC.framework"
RESOURCE_BUNDLE_NAME = "Telemachus_Telemachus.bundle"
CODESIGN_TEMP_FILE_MARKER = ".cstemp"
CODESIGN_TEMP_REFERENCE_PATTERN = re.compile(
    rf"{re.escape(CODESIGN_TEMP_FILE_MARKER)}(?:$|[.$/])",
    re.IGNORECASE,
)
CODE_SIGNATURE_DIR_NAME = "_CodeSignature"
CODE_RESOURCES_NAME = "CodeResources"
EXPECTED_BUNDLE_ID = "dev.telemachus.display"
SIGNING_CERTIFICATE_REQUIREMENT_PATTERN = re.compile(
    r'certificate\s+(leaf|root)\s*=\s*H"([0-9A-Fa-f]{40})"'
)
REPRODUCIBLE_TIMESTAMP = 315_532_800  # 1980-01-01, the ZIP timestamp floor.
SOURCE_COMMIT_PLIST_KEY = "VibeScreenSourceCommit"
SOURCE_TREE_PLIST_KEY = "VibeScreenSourceTree"
SOURCE_DIRTY_PLIST_KEY = "VibeScreenSourceDirty"
PREFLIGHT_EXTERNAL_COMMAND_TIMEOUT_SECONDS = 30
AD_HOC_PREVIEW_NOTICE_NAME = "AD_HOC_PREVIEW_NOT_FOR_TCC_OR_DEVICE_EVIDENCE.txt"
AD_HOC_PREVIEW_WARNING = (
    "WARNING: created an explicit ad-hoc signed macOS preview artifact. "
    "It changes the designated requirement and must not be used for macOS TCC "
    "or device-acceptance evidence."
)


@dataclass(frozen=True)
class SourceIdentity:
    commit: str
    tree: str
    dirty: bool


@dataclass(frozen=True)
class CodesigningIdentity:
    sha1: str
    name: str


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
        default=None,
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
    args = parser.parse_args()
    args.sign_identity_explicit = args.sign_identity is not None
    if args.sign_identity is None:
        args.sign_identity = os.environ.get(SIGN_IDENTITY_ENV, DEFAULT_SIGN_IDENTITY)
    return args


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


def normalize_sha1(value: str) -> str:
    return value.replace(" ", "").upper()


def is_sha1(value: str) -> bool:
    return re.fullmatch(r"[0-9A-Fa-f]{40}", normalize_sha1(value)) is not None


def parse_codesigning_identities(output: str) -> tuple[CodesigningIdentity, ...]:
    identities: list[CodesigningIdentity] = []
    for raw_line in output.splitlines():
        match = re.match(r'^\s*\d+\)\s+([0-9A-Fa-f]{40})\s+"(.+)"\s*$', raw_line)
        if match is None:
            continue
        identities.append(
            CodesigningIdentity(
                sha1=normalize_sha1(match.group(1)),
                name=match.group(2),
            )
        )
    return tuple(identities)


def dedupe_codesigning_identities_by_sha1(
    identities: tuple[CodesigningIdentity, ...] | list[CodesigningIdentity],
) -> tuple[CodesigningIdentity, ...]:
    unique: dict[str, CodesigningIdentity] = {}
    for identity in identities:
        unique.setdefault(identity.sha1, identity)
    return tuple(unique.values())


def parse_signing_certificate_hash(requirement: str | None) -> str | None:
    if requirement is None:
        return None
    matches = SIGNING_CERTIFICATE_REQUIREMENT_PATTERN.findall(requirement)
    for certificate_kind, sha1 in matches:
        if certificate_kind == "leaf":
            return sha1.upper()
    for certificate_kind, sha1 in matches:
        if certificate_kind == "root":
            return sha1.upper()
    return None


def resolve_sign_identity(requested: str) -> str:
    """Return a usable codesign identity argument.

    The local development Host must use the historical leaf certificate SHA-1 so
    the designated requirement, and therefore macOS Screen Recording/Accessibility
    grants, stay reusable across rebuilds. An ad-hoc signature (requested with
    '-') is only used when the operator passes it explicitly; CI workflows must
    pass '--sign-identity -' explicitly to produce ad-hoc signed preview artifacts.
    """
    if requested == "-":
        return requested
    requested_normalized = normalize_sha1(requested)
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
    if lookup.returncode != 0:
        detail = lookup.stdout.strip() or "no output"
        raise SystemExit(
            "security find-identity -v -p codesigning failed while resolving "
            f"codesign identity '{requested}': {detail}"
        )
    identities = dedupe_codesigning_identities_by_sha1(parse_codesigning_identities(lookup.stdout))
    matching_expected_leaf = [
        identity for identity in identities if identity.sha1 == EXPECTED_SIGNING_LEAF_SHA1
    ]
    if lookup.returncode == 0 and is_sha1(requested):
        if requested_normalized != EXPECTED_SIGNING_LEAF_SHA1:
            raise SystemExit(
                f"codesign identity SHA-1 '{requested_normalized}' is not the pinned "
                f"Vibe Screen Host signing leaf '{EXPECTED_SIGNING_LEAF_SHA1}'."
            )
        if len(matching_expected_leaf) == 1:
            return EXPECTED_SIGNING_LEAF_SHA1
        raise SystemExit(
            f"pinned Vibe Screen Host signing leaf '{EXPECTED_SIGNING_LEAF_SHA1}' "
            "not found in the keychain."
        )
    matching_name = [identity for identity in identities if identity.name == requested]
    if lookup.returncode == 0 and len(matching_name) == 1:
        identity = matching_name[0]
        if identity.sha1 == EXPECTED_SIGNING_LEAF_SHA1:
            return EXPECTED_SIGNING_LEAF_SHA1
        raise SystemExit(
            f"codesign identity '{requested}' has leaf SHA-1 '{identity.sha1}', "
            f"expected '{EXPECTED_SIGNING_LEAF_SHA1}'. Refusing to replace the "
            "historically authorized Host signing leaf."
        )
    if lookup.returncode == 0 and len(matching_name) > 1:
        raise SystemExit(
            f"multiple codesign identities named '{requested}' were found in the keychain. "
            f"Use the pinned SHA-1 '{EXPECTED_SIGNING_LEAF_SHA1}' or remove duplicates "
            "so local builds cannot drift to a different certificate leaf."
        )
    raise SystemExit(
        f"codesign identity '{requested}' not found in the keychain. "
        f"Import the Vibe Screen Host signing certificate with leaf SHA-1 "
        f"'{EXPECTED_SIGNING_LEAF_SHA1}' (or set ${SIGN_IDENTITY_ENV} to that "
        "SHA-1), or pass '--sign-identity -' for an explicit ad-hoc preview "
        "build. Ad-hoc signing changes the designated requirement and cannot "
        "reuse macOS Screen Recording/Accessibility grants."
    )


def require_explicit_ad_hoc_preview(sign_identity: str, *, explicit_cli_option: bool) -> None:
    if sign_identity == "-" and not explicit_cli_option:
        raise SystemExit(
            f"${SIGN_IDENTITY_ENV}=- is not accepted for macOS packaging. Pass "
            "--sign-identity - explicitly only when creating an ad-hoc preview "
            "artifact; stable local builds must resolve to the pinned Vibe Screen "
            f"Host signing leaf '{EXPECTED_SIGNING_LEAF_SHA1}'."
        )


def write_ad_hoc_preview_notice(resources_dir: Path, sign_identity: str) -> None:
    if sign_identity != "-":
        return
    (resources_dir / AD_HOC_PREVIEW_NOTICE_NAME).write_text(
        AD_HOC_PREVIEW_WARNING + "\n",
        encoding="utf-8",
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


def zip_member_destination(root: Path, member_name: str) -> Path:
    relative = Path(member_name)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise SystemExit(f"archive contains unsafe path: {member_name}")
    destination = root.joinpath(*relative.parts)
    root_resolved = root.resolve(strict=False)
    destination_resolved = destination.resolve(strict=False)
    if not destination_resolved.is_relative_to(root_resolved):
        raise SystemExit(f"archive path escapes extraction root: {member_name}")
    return destination


def extract_reproducible_zip(archive_path: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        for entry in archive.infolist():
            target = zip_member_destination(destination, entry.filename)
            mode = entry.external_attr >> 16
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                if mode:
                    target.chmod(stat.S_IMODE(mode))
                continue
            if target.exists() or target.is_symlink():
                raise SystemExit(f"archive contains duplicate path: {entry.filename}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if stat.S_IFMT(mode) == stat.S_IFLNK:
                link_target = archive.read(entry).decode("utf-8")
                if Path(link_target).is_absolute():
                    raise SystemExit(f"archive symlink target is absolute: {entry.filename}")
                link_destination = target.parent.joinpath(link_target).resolve(strict=False)
                if not link_destination.is_relative_to(destination.resolve(strict=False)):
                    raise SystemExit(f"archive symlink target escapes extraction root: {entry.filename}")
                os.symlink(link_target, target)
                continue
            target.write_bytes(archive.read(entry))
            if mode:
                target.chmod(stat.S_IMODE(mode))


def verify_reproducible_zip(
    archive_path: Path,
    app_bundle_name: str,
    *,
    sign_identity: str | None = None,
) -> None:
    with tempfile.TemporaryDirectory(prefix="vibe-screen-archive-verify.") as temporary_directory:
        extract_root = Path(temporary_directory)
        extract_reproducible_zip(archive_path, extract_root)
        extracted_app = extract_root / app_bundle_name
        if not extracted_app.is_dir():
            raise SystemExit(f"archive omitted expected app bundle: {app_bundle_name}")
        require_no_codesign_resource_seal_temporary_references(extracted_app)
        run(CODESIGN, "--verify", "--deep", "--strict", "--verbose=2", str(extracted_app))
        if sign_identity is not None:
            verify_packaged_app_certificate_contracts(extracted_app, sign_identity)
        require_no_codesign_temporary_files(extracted_app)
        require_no_codesign_resource_seal_temporary_references(extracted_app)


def codesign_temporary_files(root: Path) -> tuple[Path, ...]:
    """Return codesign replacement files that must not enter resource seals."""
    if not root.exists():
        return ()
    return tuple(
        sorted(
            (path for path in root.rglob("*") if value_references_codesign_temporary_file(path.name)),
            key=lambda item: item.relative_to(root).as_posix(),
        )
    )


def clean_codesign_temporary_files(root: Path) -> tuple[Path, ...]:
    temporary_files = codesign_temporary_files(root)
    for path in sorted(temporary_files, key=lambda item: len(item.parts), reverse=True):
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    return temporary_files


def require_no_codesign_temporary_files(root: Path) -> None:
    temporary_files = codesign_temporary_files(root)
    if temporary_files:
        relative_paths = ", ".join(path.relative_to(root).as_posix() for path in temporary_files)
        raise SystemExit(
            f"codesign temporary files remain in {root}: "
            f"{relative_paths}. Refusing to continue because those files can be sealed "
            "into package artifacts and make strict verification fail."
        )


def codesign_resource_seal_files(root: Path) -> tuple[Path, ...]:
    if not root.exists():
        return ()
    return tuple(
        sorted(
            (
                path
                for path in root.rglob(CODE_RESOURCES_NAME)
                if path.parent.name == CODE_SIGNATURE_DIR_NAME
            ),
            key=lambda item: item.relative_to(root).as_posix(),
        )
    )


def value_references_codesign_temporary_file(value: object) -> bool:
    return isinstance(value, str) and CODESIGN_TEMP_REFERENCE_PATTERN.search(value) is not None


def codesign_resource_seal_temporary_references(root: Path) -> tuple[str, ...]:
    findings: list[str] = []
    for manifest in codesign_resource_seal_files(root):
        try:
            with manifest.open("rb") as manifest_file:
                payload = plistlib.load(manifest_file)
        except (OSError, plistlib.InvalidFileException, ValueError, TypeError) as error:
            raise SystemExit(
                f"codesign resource seal is unreadable or malformed at "
                f"{manifest.relative_to(root).as_posix()}: {error}"
            ) from error
        manifest_prefix = manifest.relative_to(root).as_posix()
        findings.extend(
            f"{manifest_prefix}:{reference}"
            for reference in temporary_references_in_plist(payload)
        )
    return tuple(findings)


def temporary_references_in_plist(value: object, prefix: str = "$") -> tuple[str, ...]:
    findings: list[str] = []
    if isinstance(value, dict):
        for raw_key, item in value.items():
            key = str(raw_key)
            path = f"{prefix}/{key}"
            if value_references_codesign_temporary_file(key):
                findings.append(path)
            findings.extend(temporary_references_in_plist(item, path))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            findings.extend(temporary_references_in_plist(item, f"{prefix}[{index}]"))
    elif value_references_codesign_temporary_file(value):
        findings.append(f"{prefix}={value}")
    return tuple(findings)


def require_no_codesign_resource_seal_temporary_references(root: Path) -> None:
    references = codesign_resource_seal_temporary_references(root)
    if references:
        raise SystemExit(
            f"codesign resource seals in {root} reference temporary files: "
            f"{', '.join(references)}. Refusing to continue because stale "
            "CodeResources entries can make strict verification fail and change "
            "macOS TCC identity matching."
        )


def parse_designated_requirement(output: str) -> str | None:
    for line in output.splitlines():
        if "designated =>" in line:
            return line.split("designated =>", 1)[1].strip()
    return None


def parse_designated_requirement_identifier(requirement: str | None) -> str | None:
    if requirement is None:
        return None
    quoted = re.search(r'\bidentifier\s+"([^"]+)"', requirement)
    if quoted is not None:
        return quoted.group(1)
    bare = re.search(r"\bidentifier\s+([^\s);]+)", requirement)
    if bare is not None:
        return bare.group(1)
    return None


def verify_signed_app_certificate_contract(
    app_path: Path,
    sign_identity: str,
    *,
    expected_identifier: str = EXPECTED_BUNDLE_ID,
) -> None:
    try:
        requirement_output = run(CODESIGN, "-d", "-r-", str(app_path))
    except subprocess.CalledProcessError as error:
        detail = error.output.strip() if error.output else "no output"
        raise SystemExit(
            f"codesign designated requirement inspection failed for {app_path}: {detail}"
        ) from error
    requirement = parse_designated_requirement(requirement_output)
    if not requirement:
        raise SystemExit(f"codesign designated requirement is missing for {app_path}")
    identifier = parse_designated_requirement_identifier(requirement)
    if identifier is None and sign_identity == "-":
        return
    if identifier != expected_identifier:
        actual_identifier = identifier or "missing"
        raise SystemExit(
            f"codesign designated requirement for {app_path} uses identifier "
            f"'{actual_identifier}', expected '{expected_identifier}'"
        )
    if sign_identity == "-":
        return
    certificate_hash = parse_signing_certificate_hash(requirement)
    if certificate_hash is None:
        raise SystemExit(
            f"codesign designated requirement for {app_path} does not contain a "
            "valid certificate leaf/root SHA-1"
        )
    if certificate_hash != EXPECTED_SIGNING_LEAF_SHA1:
        raise SystemExit(
            f"codesign designated requirement for {app_path} uses certificate SHA-1 "
            f"'{certificate_hash}', expected '{EXPECTED_SIGNING_LEAF_SHA1}'"
        )


def verify_packaged_app_certificate_contracts(app_path: Path, sign_identity: str) -> None:
    verify_signed_app_certificate_contract(
        app_path,
        sign_identity,
        expected_identifier=EXPECTED_BUNDLE_ID,
    )
    web_rtc_framework = app_path / "Contents" / "Frameworks" / WEBRTC_FRAMEWORK_NAME
    if web_rtc_framework.exists():
        verify_signed_app_certificate_contract(
            web_rtc_framework,
            sign_identity,
            expected_identifier="org.webrtc.WebRTC",
        )


def sign_packaged_app(app_path: Path, web_rtc_framework: Path, sign_identity: str) -> None:
    clean_codesign_temporary_files(web_rtc_framework)
    require_no_codesign_temporary_files(web_rtc_framework)
    run(
        CODESIGN,
        "--force",
        "--sign",
        sign_identity,
        str(web_rtc_framework),
    )
    require_no_codesign_resource_seal_temporary_references(web_rtc_framework)
    run(CODESIGN, "--verify", "--strict", "--verbose=2", str(web_rtc_framework))
    require_no_codesign_temporary_files(web_rtc_framework)
    require_no_codesign_resource_seal_temporary_references(web_rtc_framework)
    clean_codesign_temporary_files(app_path)
    require_no_codesign_temporary_files(app_path)
    run(
        CODESIGN,
        "--force",
        "--sign",
        sign_identity,
        "--entitlements",
        str(HOST_ROOT / "Telemachus.entitlements"),
        str(app_path),
    )
    require_no_codesign_resource_seal_temporary_references(app_path)
    run(CODESIGN, "--verify", "--deep", "--strict", "--verbose=2", str(app_path))
    require_no_codesign_temporary_files(app_path)
    require_no_codesign_resource_seal_temporary_references(app_path)
    verify_packaged_app_certificate_contracts(app_path, sign_identity)


def main() -> int:
    args = parse_args()
    require_explicit_ad_hoc_preview(
        args.sign_identity,
        explicit_cli_option=getattr(args, "sign_identity_explicit", False),
    )
    sign_identity = resolve_sign_identity(args.sign_identity)
    validate_notice_bundle(REPOSITORY_ROOT)
    source_identity = collect_source_identity(REPOSITORY_ROOT)
    if source_identity.dirty:
        raise SystemExit(
            "refusing to package macOS Host from a dirty source tree; "
            "commit or discard local changes before running scripts/package_macos.py"
        )
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
    write_ad_hoc_preview_notice(resources_dir, sign_identity)
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

    sign_packaged_app(app_path, frameworks_dir / WEBRTC_FRAMEWORK_NAME, sign_identity)
    normalize_mtimes(app_path)
    create_reproducible_zip(app_path, archive_path)
    verify_reproducible_zip(archive_path, f"{PRODUCT_NAME}.app", sign_identity=sign_identity)
    checksum_path.write_text(
        f"{sha256(archive_path)}  {archive_path.name}\n",
        encoding="utf-8",
    )
    if sign_identity == "-":
        print(AD_HOC_PREVIEW_WARNING, file=sys.stderr)
    print(app_path)
    print(archive_path)
    print(checksum_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
