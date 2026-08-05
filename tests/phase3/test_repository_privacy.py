from __future__ import annotations

import ipaddress
import re
import subprocess
import unittest
from hashlib import sha256
from pathlib import Path
from urllib.parse import unquote

from scripts.phase3.evidence_privacy import (
    DERIVED_FILES,
    build_manifest,
    scan_content,
    serialized_manifest,
)


ROOT = Path(__file__).resolve().parents[2]
PHASE3_EVIDENCE = (
    ROOT
    / "docs/changes/2026-08-04-phase-3-secure-internet/evidence"
    / "2026-08-05-nubia-p0110-internet"
)
MARKDOWN_LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
CARRIER_GRADE_NAT = ipaddress.ip_network("100." + "64.0.0/10")
IPV4_ENDPOINT_PATTERN = re.compile(
    rb"(?<![0-9.])((?:[0-9]{1,3}\.){3}[0-9]{1,3})(?:[:-][0-9]{1,5})?(?![0-9.])"
)
ACL_CGNAT_FIXTURE_ADDRESS = b"100." + b"64.0.1"
ACL_CGNAT_FIXTURE_LINE = (
    b"for peer_address in 10.0.0.1 "
    + ACL_CGNAT_FIXTURE_ADDRESS
    + b" 169.254.169.254 172.16.0.1 192.168.0.1 198.18.0.1; do"
)
CGNAT_EXACT_FIXTURE_LINES = {
    Path("services/relay/integration/test-turn-peer-acl.sh"): (
        ACL_CGNAT_FIXTURE_LINE,
    ),
}


def contains_cgnat_endpoint(content: bytes) -> bool:
    for match in IPV4_ENDPOINT_PATTERN.finditer(content):
        try:
            address = ipaddress.ip_address(match.group(1).decode("ascii"))
        except ValueError:
            continue
        suffix = content[match.end() :]
        prefix = content[: match.start()]
        is_cidr = re.match(rb"/[0-9]{1,2}(?![0-9])", suffix) is not None
        is_range_start = re.match(
            rb"-(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9.])", suffix
        ) is not None
        is_range_end = re.search(
            rb"(?:[0-9]{1,3}\.){3}[0-9]{1,3}-$", prefix
        ) is not None
        if address in CARRIER_GRADE_NAT and not is_cidr and not is_range_start and not is_range_end:
            return True
    return False


def remove_exact_cgnat_fixtures(relative_path: Path, content: bytes) -> tuple[bytes, list[str]]:
    errors = []
    lines = content.splitlines(keepends=True)
    for fixture_line in CGNAT_EXACT_FIXTURE_LINES.get(relative_path, ()):
        matching_indices = [
            index
            for index, line in enumerate(lines)
            if line.rstrip(b"\r\n") == fixture_line
        ]
        if len(matching_indices) != 1:
            errors.append(f"fixture-line-count:{relative_path}:1:{len(matching_indices)}")
            continue
        index = matching_indices[0]
        newline = b"\r\n" if lines[index].endswith(b"\r\n") else b"\n"
        if not lines[index].endswith((b"\n", b"\r")):
            newline = b""
        lines[index] = b"<allowlisted-cgnat-acl-fixture-line>" + newline
    return b"".join(lines), errors


class RepositoryPrivacyTests(unittest.TestCase):
    def test_current_tree_has_no_device_endpoint(self) -> None:
        violations = []
        listed = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout
        for raw_path in listed.split(b"\0"):
            if not raw_path:
                continue
            relative_path = Path(raw_path.decode("utf-8"))
            path = ROOT / relative_path
            if not path.is_file():
                continue
            content = path.read_bytes()
            if contains_cgnat_endpoint(raw_path):
                violations.append(f"endpoint-path:{relative_path}")
            content, fixture_errors = remove_exact_cgnat_fixtures(relative_path, content)
            violations.extend(fixture_errors)
            if contains_cgnat_endpoint(content):
                violations.append(f"endpoint-content:{relative_path}")
        self.assertEqual(violations, [])

    def test_cgnat_endpoint_variants_are_rejected_without_version_false_positives(self) -> None:
        address = b"100." + b"72.1.2"
        prohibited = {
            "bare-ip": address,
            "ip-port": address + b":5555",
            "device-ip-path": b"evidence/device-" + address + b"/README.md",
            "device-ip-port-path": b"evidence/device-" + address + b"-5555/README.md",
            "hyphen-endpoint": b"endpoint-" + address + b"-5555",
        }
        for variant, content in prohibited.items():
            with self.subTest(variant=variant):
                self.assertTrue(contains_cgnat_endpoint(content))

        allowed = (
            b"swiftlang-6.3.1.1.2",
            b"documentation-peer=192.0.2.10:5555",
            b"lan-pairing=192.168.1.42:8888",
            b"denied-peer-ip=" + b"100." + b"64.0.0/10",
            b"denied-peer-ip=" + b"100." + b"64.0.0-" + b"100." + b"127.255.255",
        )
        for content in allowed:
            with self.subTest(allowed=content):
                self.assertFalse(contains_cgnat_endpoint(content))

    def test_exact_acl_fixture_does_not_allow_additional_cgnat_content(self) -> None:
        fixture_path = Path("services/relay/integration/test-turn-peer-acl.sh")
        fixture_line = ACL_CGNAT_FIXTURE_LINE
        sanitized, errors = remove_exact_cgnat_fixtures(fixture_path, fixture_line + b"\n")
        self.assertEqual(errors, [])
        self.assertFalse(contains_cgnat_endpoint(sanitized))

        extra_endpoint = b"100." + b"72.9.8"
        sanitized, errors = remove_exact_cgnat_fixtures(
            fixture_path, fixture_line + b"\nleak=" + extra_endpoint + b"\n"
        )
        self.assertEqual(errors, [])
        self.assertTrue(contains_cgnat_endpoint(sanitized))

        collisions = (
            ACL_CGNAT_FIXTURE_ADDRESS + b":5555",
            ACL_CGNAT_FIXTURE_ADDRESS + b"-5555",
            ACL_CGNAT_FIXTURE_ADDRESS + b"0:5555",
        )
        for collision in collisions:
            content = fixture_line.replace(ACL_CGNAT_FIXTURE_ADDRESS, collision) + b"\n"
            with self.subTest(collision=collision):
                sanitized, errors = remove_exact_cgnat_fixtures(fixture_path, content)
                self.assertTrue(errors)
                self.assertTrue(contains_cgnat_endpoint(sanitized))

        for content in (b"no fixture", fixture_line + b"\n" + fixture_line + b"\n"):
            with self.subTest(content=content):
                _, errors = remove_exact_cgnat_fixtures(fixture_path, content)
                self.assertTrue(errors)

    def test_phase3_evidence_privacy_manifest_matches_tree(self) -> None:
        manifest = PHASE3_EVIDENCE / "privacy-scan.json"
        expected = serialized_manifest(build_manifest(PHASE3_EVIDENCE))
        self.assertEqual(manifest.read_bytes(), expected)
        self.assertEqual(build_manifest(PHASE3_EVIDENCE)["result"], "pass")
        for derived_name in DERIVED_FILES:
            with self.subTest(derived_name=derived_name):
                self.assertEqual(scan_content((PHASE3_EVIDENCE / derived_name).read_bytes()), {})

    def test_phase3_privacy_rules_reject_each_sensitive_category(self) -> None:
        fixtures = {
            "network_endpoint": b"peer=" + b"100." + b"72.1.2:5555",
            "hardware_identifier": b'"hardware_serial": "DEVICE-UNIQUE-123"',
            "credential_material": b'"token": "sensitive-token-value"',
            "url": b"https://private.example.invalid/session",
            "user_absolute_path": b"/Users/private-account/work/evidence.log",
        }
        for category, content in fixtures.items():
            with self.subTest(category=category):
                self.assertIn(category, scan_content(content))
        self.assertEqual(scan_content(b"swiftlang-6.3.1.1.2 and <redacted-ip>"), {})

    def test_phase3_privacy_rules_reject_project_credential_schemas(self) -> None:
        sensitive_keys = (
            b"credential",
            b"ice_credential",
            b"one_time_credential",
            b"device_token",
            b"host_token",
            b"access_token",
            b"signaling_token",
            b"shared_secret",
            b"bootstrap_secret",
            b"shared_secret_base64",
            b"bootstrap_secret_base64",
            b"sharedSecretBase64",
            b"bootstrapSecretBase64",
            b"pairing_secret",
            b"session_secret",
            b"turn_password",
        )
        sensitive_value = b"fixture-" + b"not-a-real-secret"
        for key in sensitive_keys:
            assignments = (
                b'{"' + key + b'":"' + sensitive_value + b'"}',
                key + b"=" + sensitive_value,
                b"VIBE_" + key.upper() + b"='" + sensitive_value + b"'",
            )
            for assignment in assignments:
                with self.subTest(key=key, assignment=assignment.split(b"=", maxsplit=1)[0]):
                    findings = scan_content(assignment).get("credential_material", [])
                    self.assertTrue(findings)
                    self.assertTrue(all(value.startswith("sha256:") for value in findings))

        direct_material = (
            b"Authorization: Bearer " + sensitive_value,
            b"-----BEGIN PRIVATE " + b"KEY-----",
            b"device_token=$" + b"uper-secret-value",
        )
        for content in direct_material:
            with self.subTest(direct_material=content[:20]):
                self.assertIn("credential_material", scan_content(content))

        safe_values = (
            b'{"device_token":"<redacted>"}',
            b'{"credential":null}',
            b"SHARED_SECRET=${VIBE_SHARED_SECRET_FILE}",
        )
        for content in safe_values:
            with self.subTest(safe_value=content):
                self.assertNotIn("credential_material", scan_content(content))

    def test_phase3_evidence_sha256s_cover_every_archived_file(self) -> None:
        checksum_path = PHASE3_EVIDENCE / "SHA256SUMS"
        recorded = {}
        for line in checksum_path.read_text(encoding="utf-8").splitlines():
            digest, relative = line.split("  ./", maxsplit=1)
            self.assertRegex(digest, r"^[0-9a-f]{64}$")
            self.assertNotIn(relative, recorded)
            recorded[relative] = digest

        expected_paths = {
            path.relative_to(PHASE3_EVIDENCE).as_posix()
            for path in PHASE3_EVIDENCE.rglob("*")
            if path.is_file() and path.name != "SHA256SUMS"
        }
        self.assertEqual(set(recorded), expected_paths)
        for relative, digest in recorded.items():
            self.assertEqual(sha256((PHASE3_EVIDENCE / relative).read_bytes()).hexdigest(), digest)

    def test_delivery_document_links_resolve(self) -> None:
        documents = [
            ROOT / "README.md",
            ROOT / "docs/changes/2026-08-04-phase-0-baseline/TEST.md",
            ROOT / "docs/changes/2026-08-05-phase-1-android-client/TEST.md",
            ROOT / "docs/changes/2026-08-04-phase-3-secure-internet/TECH.md",
            ROOT / "docs/changes/2026-08-04-phase-3-secure-internet/TEST.md",
            PHASE3_EVIDENCE / "README.md",
        ]
        missing = []
        for document in documents:
            for raw_target in MARKDOWN_LINK_PATTERN.findall(document.read_text(encoding="utf-8")):
                target = raw_target.strip().strip("<>").split("#", maxsplit=1)[0]
                if not target or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE):
                    continue
                resolved = (document.parent / unquote(target)).resolve()
                if not resolved.exists():
                    missing.append(f"{document.relative_to(ROOT)} -> {target}")
        self.assertEqual(missing, [])

    def test_makefile_has_no_device_endpoint_default(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        self.assertIn("EVIDENCE_SERIAL ?=\n", makefile)
        self.assertIn("error: set EVIDENCE_SERIAL explicitly", makefile)


if __name__ == "__main__":
    unittest.main()
