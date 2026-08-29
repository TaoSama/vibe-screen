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
ADB_SERIAL_COMMAND_PATTERN = re.compile(rb"\badb\s+-s\s+(?P<serial>\S+)", re.IGNORECASE)
SSH_COMMAND_TARGET_PATTERN = re.compile(rb"\bssh\s+(?P<target>\S+)")
PUBLIC_DEPLOYMENT_DOCS = (
    Path("DEPLOY.md"),
    Path(".claude/skills/deploy/SKILL.md"),
)
PUBLIC_RELAY_SSH_ALIAS_PLACEHOLDER = b"<relay-host-ssh-alias>"
RAW_ANDROID_SERIAL_PROPERTY_PATTERN = re.compile(
    rb"(?im)^ro\.serialno=(?:[0-9a-f]{8}|EP[0-9A-Z]{16})$"
)
RAW_XIAOMI_EVIDENCE_PATH_PATTERN = re.compile(
    rb"xiaomi(?:12|13)-fuxi-[0-9a-f]{8}(?:[-/]|\b)", re.IGNORECASE
)
RAW_ANDROID_SERIAL_TOKEN_PATTERN = re.compile(rb"(?:[0-9a-f]{8}|EP[0-9A-Z]{16})", re.IGNORECASE)
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


def contains_raw_adb_serial_command(content: bytes) -> bool:
    for match in ADB_SERIAL_COMMAND_PATTERN.finditer(content):
        serial = match.group("serial").strip().strip(b"`\"'.,);")
        if b"REDACTED" in serial.upper():
            continue
        if RAW_ANDROID_SERIAL_TOKEN_PATTERN.fullmatch(serial):
            return True
    return False


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

    def test_current_tree_has_no_raw_android_serial_contexts(self) -> None:
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
            if RAW_XIAOMI_EVIDENCE_PATH_PATTERN.search(raw_path):
                violations.append(f"xiaomi-serial-path:{relative_path}")
            if not path.is_file():
                continue
            content = path.read_bytes()
            if contains_raw_adb_serial_command(content):
                violations.append(f"adb-serial-command:{relative_path}")
            if RAW_ANDROID_SERIAL_PROPERTY_PATTERN.search(content):
                violations.append(f"android-serial-property:{relative_path}")
            if RAW_XIAOMI_EVIDENCE_PATH_PATTERN.search(content):
                violations.append(f"xiaomi-serial-content:{relative_path}")
        self.assertEqual(violations, [])

    def test_android_serial_contexts_reject_raw_values(self) -> None:
        hex_serial = b"dead" + b"beef"
        long_serial = b"EP123456" + b"7890ABCDEF"
        prohibited = (
            b"adb -s " + hex_serial + b" shell get-state",
            b"adb -s " + long_serial + b" shell get-state",
            b"ro.serialno=" + hex_serial,
            b"ro.serialno=" + long_serial,
            b"evidence/2026-08-08-xiaomi12-fuxi-" + hex_serial + b"/README.md",
            b"evidence/2026-08-10-xiaomi13-fuxi-" + hex_serial + b"-30m/README.md",
        )
        for content in prohibited:
            with self.subTest(content=content):
                self.assertTrue(
                    contains_raw_adb_serial_command(content)
                    or RAW_ANDROID_SERIAL_PROPERTY_PATTERN.search(content)
                    or RAW_XIAOMI_EVIDENCE_PATH_PATTERN.search(content)
                )

        allowed = (
            b"adb -s <redacted-adb-serial> shell get-state",
            b"adb -s REDACTED_P0110_USB_SERIAL shell get-state",
            b"adb -s $EVIDENCE_SERIAL shell get-state",
            b"adb -s DEVICE_HOST:5555 shell get-state",
            b"adb -s test-p0110-adb-serial shell get-state",
            b"ro.serialno=<redacted-adb-serial>",
            b"ro.serialno=REDACTED_P0110_USB_SERIAL",
            b"evidence/2026-08-08-xiaomi12-fuxi-redacted/README.md",
            b"evidence/2026-08-10-xiaomi13-fuxi-redacted-30m/README.md",
        )
        for content in allowed:
            with self.subTest(content=content):
                self.assertFalse(contains_raw_adb_serial_command(content))
                self.assertFalse(RAW_ANDROID_SERIAL_PROPERTY_PATTERN.search(content))
                self.assertFalse(RAW_XIAOMI_EVIDENCE_PATH_PATTERN.search(content))

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
            "adb_identifier": b'"adb_serial": "DEVICE-UNIQUE-123"',
            "credential_material": b'"token": "sensitive-token-value"',
            "url": b"https://private.example.invalid/session",
            "user_absolute_path": b"/Users/private-account/work/evidence.log",
        }
        for category, content in fixtures.items():
            with self.subTest(category=category):
                expected_category = "hardware_identifier" if category == "adb_identifier" else category
                self.assertIn(expected_category, scan_content(content))

    def test_public_deployment_docs_use_placeholder_ssh_alias(self) -> None:
        violations = []
        for relative_path in PUBLIC_DEPLOYMENT_DOCS:
            content = (ROOT / relative_path).read_bytes()
            for match in SSH_COMMAND_TARGET_PATTERN.finditer(content):
                target = match.group("target").strip(b"'\".,);")
                if target != PUBLIC_RELAY_SSH_ALIAS_PLACEHOLDER:
                    violations.append(f"ssh-target:{relative_path}")
        self.assertEqual(violations, [])
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

    def test_phase3_privacy_rules_allow_json_safe_literals_only(self) -> None:
        safe_literals = (
            b'{"writes_pairing_token": false}',
            b'{"writes_pairing_token": true}',
            b'{"writes_pairing_token": null}',
            b'{"maximum_token_bytes": 1048576}',
            b'{"credential": ""}',
        )
        for content in safe_literals:
            with self.subTest(content=content):
                self.assertEqual(scan_content(content), {})

        findings = scan_content(b'{"token": "sensitive-token-value"}')
        self.assertIn("credential_material", findings)
        self.assertTrue(all(value.startswith("sha256:") for value in findings["credential_material"]))

        numeric_string_findings = scan_content(b'{"token":"12345"}')
        self.assertIn("credential_material", numeric_string_findings)
        self.assertTrue(
            all(value.startswith("sha256:") for value in numeric_string_findings["credential_material"])
        )

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

    def test_makefile_exposes_fail_closed_phase3_internet_soak_gate(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        for phrase in (
            "phase3-internet-soak-manifest:",
            "phase3-internet-soak-gate:",
            "vibescreen_evidence.phase3_internet_soak manifest",
            "vibescreen_evidence.phase3_internet_soak gate",
            "PHASE3_INTERNET_ALLOW_BLOCKED",
            "PHASE3_INTERNET_REMOTE_TURN_REPORT",
            "PHASE3_INTERNET_REVOCATION_REPORT",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, makefile)


if __name__ == "__main__":
    unittest.main()
