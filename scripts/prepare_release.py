#!/usr/bin/env python3
"""Validate a preview release and assemble checksums, notices, notes, and SBOM."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path

from archive_artifact import create_deterministic_zip


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SEMVER_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
ANDROID_VERSION_COMPONENT_MAX = 99
ANDROID_VERSION_CODE_BASE = 100_000
ANDROID_VERSION_CODE_MAX = 2_100_000_000
EXPECTED_ARTIFACT_PATTERNS = {
    "macOS": "Telemachus-macos-{version}-*.zip",
    "Android": "Telemachus-android-{version}-debug.apk",
    "iOS Simulator": "VibeScreen-ios-simulator-{version}.zip",
}
SWIFT_DEPENDENCIES = {
    "webrtc": {
        "license": "BSD-3-Clause",
        "purl_name": "stasel/WebRTC",
    },
    "swift-protobuf": {
        "license": "Apache-2.0 WITH Swift-exception",
        "purl_name": "apple/swift-protobuf",
    },
}
NOTICE_PATHS = (
    "LICENSE",
    "NOTICE",
    "THIRD_PARTY.md",
    "baseline/LICENSE",
    "baseline/NOTICE",
    "baseline/licenses",
    "third_party/gson",
    "third_party/telemachus",
    "third_party/webrtc-android",
    "baseline/MacHost/Sources/Phase3/InternetTransport/ThirdParty",
    "apps/ios/THIRD_PARTY.md",
    "apps/ios/ThirdPartyLicenses",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="Release version without the leading v.")
    parser.add_argument("--tag", required=True, help="Git tag, which must be v<version>.")
    parser.add_argument("--commit", required=True, help="Full release commit SHA.")
    parser.add_argument("--created", required=True, help="Release commit timestamp in ISO-8601 form.")
    parser.add_argument("--artifacts-dir", type=Path, help="Downloaded build artifacts.")
    parser.add_argument("--output-dir", type=Path, help="Directory for publishable metadata.")
    parser.add_argument("--validate-only", action="store_true", help="Only validate release identity.")
    return parser.parse_args()


def validate_identity(version: str, tag: str, commit: str, created: str) -> str:
    match = SEMVER_PATTERN.fullmatch(version)
    if match is None:
        raise ValueError(f"release version must be stable SemVer MAJOR.MINOR.PATCH: {version}")
    major, minor, patch = (int(component) for component in match.groups())
    if minor > ANDROID_VERSION_COMPONENT_MAX or patch > ANDROID_VERSION_COMPONENT_MAX:
        raise ValueError("minor and patch versions must be at most 99 for the Android versionCode")
    android_version_code = ANDROID_VERSION_CODE_BASE + major * 10_000 + minor * 100 + patch
    if android_version_code > ANDROID_VERSION_CODE_MAX:
        raise ValueError(f"version {version} exceeds the Android versionCode limit")
    if tag != f"v{version}":
        raise ValueError(f"tag {tag!r} does not match version {version!r}")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("commit must be a full lowercase 40-character Git SHA")
    normalized_created = created.replace("Z", "+00:00")
    parsed_created = dt.datetime.fromisoformat(normalized_created)
    if parsed_created.tzinfo is None:
        raise ValueError("created timestamp must include a timezone")
    return (
        parsed_created.astimezone(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def one_artifact(artifacts_dir: Path, label: str, pattern: str) -> Path:
    matches = sorted(path for path in artifacts_dir.rglob(pattern) if path.is_file())
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {label} artifact matching {pattern!r}, found {len(matches)}")
    return matches[0]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_android_packages(artifacts_dir: Path) -> list[dict[str, object]]:
    sbom_files = sorted(artifacts_dir.rglob("android-runtime.spdx.json"))
    if len(sbom_files) != 1:
        raise ValueError(f"expected exactly one Android SPDX SBOM, found {len(sbom_files)}")
    document = json.loads(sbom_files[0].read_text(encoding="utf-8"))
    packages = document.get("packages")
    if not isinstance(packages, list) or not packages:
        raise ValueError("Android SPDX SBOM contains no packages")
    normalized_packages = []
    for package in packages:
        normalized = dict(package)
        normalized["SPDXID"] = "SPDXRef-" + re.sub(
            r"[^A-Za-z0-9.-]",
            "-",
            str(normalized["SPDXID"]).removeprefix("SPDXRef-"),
        )
        normalized["filesAnalyzed"] = False
        normalized.setdefault("copyrightText", "NOASSERTION")
        normalized_packages.append(normalized)
    return normalized_packages


def load_swift_packages(resolved_path: Path) -> list[dict[str, object]]:
    document = json.loads(resolved_path.read_text(encoding="utf-8"))
    packages: list[dict[str, object]] = []
    for pin in document.get("pins", []):
        identity = pin["identity"]
        metadata = SWIFT_DEPENDENCIES.get(identity)
        if metadata is None:
            raise ValueError(f"unreviewed Swift runtime dependency in {resolved_path}: {identity}")
        state = pin["state"]
        revision = state["revision"]
        version = state.get("version", revision)
        spdx_id = "SPDXRef-Package-" + re.sub(r"[^A-Za-z0-9.-]", "-", identity)
        packages.append(
            {
                "SPDXID": spdx_id,
                "name": identity,
                "versionInfo": version,
                "downloadLocation": pin["location"],
                "filesAnalyzed": False,
                "licenseConcluded": metadata["license"],
                "licenseDeclared": metadata["license"],
                "copyrightText": "NOASSERTION",
                "externalRefs": [
                    {
                        "referenceCategory": "PACKAGE-MANAGER",
                        "referenceType": "purl",
                        "referenceLocator": f"pkg:github/{metadata['purl_name']}@{revision}",
                    }
                ],
            }
        )
    return packages


def write_release_sbom(
    version: str,
    commit: str,
    created: str,
    artifacts_dir: Path,
    output: Path,
) -> None:
    packages = load_android_packages(artifacts_dir)
    for resolved_path in (
        REPOSITORY_ROOT / "baseline/MacHost/Package.resolved",
        REPOSITORY_ROOT / "apps/ios/Package.resolved",
    ):
        packages.extend(load_swift_packages(resolved_path))
    packages_by_id: dict[str, dict[str, object]] = {}
    for package in packages:
        package_id = str(package["SPDXID"])
        existing = packages_by_id.get(package_id)
        if existing is not None and existing != package:
            raise ValueError(f"runtime dependency SPDX identifier has conflicting metadata: {package_id}")
        packages_by_id[package_id] = package
    packages = sorted(packages_by_id.values(), key=lambda package: str(package["SPDXID"]))
    package_ids = [str(package["SPDXID"]) for package in packages]
    document = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"vibe-screen-{version}-runtime-dependencies",
        "documentNamespace": f"https://github.com/TaoSama/vibe-screen/releases/tag/v{version}/sbom/{commit}",
        "creationInfo": {"created": created, "creators": ["Tool: vibe-screen-prepare-release-v1"]},
        "packages": packages,
        "relationships": [
            {
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relationshipType": "DESCRIBES",
                "relatedSpdxElement": package_id,
            }
            for package_id in package_ids
        ],
    }
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_notices_archive(version: str, artifacts_dir: Path, output: Path) -> None:
    reports = sorted(artifacts_dir.rglob("ANDROID_RUNTIME_DEPENDENCY_LICENSES.md"))
    if len(reports) != 1:
        raise ValueError(f"expected exactly one Android dependency license report, found {len(reports)}")
    with tempfile.TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory) / f"vibe-screen-{version}-notices"
        for relative in NOTICE_PATHS:
            source = REPOSITORY_ROOT / relative
            if not source.exists():
                raise FileNotFoundError(f"required notice input is missing: {relative}")
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, destination)
            else:
                shutil.copy2(source, destination)
        shutil.copy2(reports[0], root / "ANDROID_RUNTIME_DEPENDENCY_LICENSES.md")
        create_deterministic_zip(root, output)


def render_release_notes(version: str, tag: str, commit: str, output: Path) -> None:
    template = (REPOSITORY_ROOT / ".github/RELEASE_TEMPLATE.md").read_text(encoding="utf-8")
    rendered = template.replace("{{VERSION}}", version).replace("{{TAG}}", tag).replace("{{COMMIT}}", commit)
    if "{{" in rendered or "}}" in rendered:
        raise ValueError("release notes template contains an unresolved placeholder")
    output.write_text(rendered, encoding="utf-8")


def main() -> int:
    args = parse_args()
    created = validate_identity(args.version, args.tag, args.commit, args.created)
    if args.validate_only:
        return 0
    if args.artifacts_dir is None or args.output_dir is None:
        raise ValueError("--artifacts-dir and --output-dir are required unless --validate-only is used")

    artifacts_dir = args.artifacts_dir.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    selected_artifacts = [
        one_artifact(artifacts_dir, label, pattern.format(version=args.version))
        for label, pattern in EXPECTED_ARTIFACT_PATTERNS.items()
    ]
    published_artifacts = []
    for artifact in selected_artifacts:
        destination = output_dir / artifact.name
        if artifact.resolve() != destination.resolve():
            shutil.copy2(artifact, destination)
        published_artifacts.append(destination)

    sbom_path = output_dir / f"vibe-screen-{args.version}.spdx.json"
    notices_path = output_dir / f"vibe-screen-{args.version}-notices.zip"
    notes_path = output_dir / "RELEASE_NOTES.md"
    write_release_sbom(args.version, args.commit, created, artifacts_dir, sbom_path)
    write_notices_archive(args.version, artifacts_dir, notices_path)
    render_release_notes(args.version, args.tag, args.commit, notes_path)

    checksums_path = output_dir / "SHA256SUMS"
    checksum_targets = sorted([*published_artifacts, sbom_path, notices_path])
    checksums_path.write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in checksum_targets),
        encoding="utf-8",
    )
    for path in sorted(output_dir.iterdir()):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
