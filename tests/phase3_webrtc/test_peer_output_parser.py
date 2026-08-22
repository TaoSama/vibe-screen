from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.phase3_webrtc.model import E2EFailure
from scripts.phase3_webrtc.session import validate_peer_output


def transport_record(route: str = "direct", protocol: str = "udp") -> str:
    candidate = "relay" if route == "relay" else "host"
    return (
        "Phase 3 WebRTC signaling self-test: PASS "
        "(peerConnection=true, iceRestart=not-run, applicationE2EE=true, "
        "transmissionEpochAdvanced=true, staleContextRejected=true, "
        "controlOrderedReliableBidirectional=true, "
        "mediaUnorderedZeroRetransmitBidirectional=true, "
        f"selectedCandidatePair={route}(local={candidate},remote={candidate},"
        f"protocol={protocol}))"
    )


def product_record(
    route: str = "direct",
    protocol: str = "udp",
    application_e2ee: str = "true",
) -> str:
    candidate = "relay" if route == "relay" else "host"
    return (
        "Phase 3 product signaling self-test: PASS "
        f"(productSession=true, protocolV1=true, route={route}, epoch=1, "
        "configEpoch=2, rotation=90, mediaSource=videotoolbox-hevc, "
        "keyframe=true, delta=true, input=true, "
        f"applicationE2EE={application_e2ee}, "
        f"selectedCandidatePair={route}(local={candidate},remote={candidate},"
        f"protocol={protocol}), controlChannel=ordered-reliable, "
        "mediaChannel=unordered-zero-retransmit)"
    )


class PeerOutputParserTests(unittest.TestCase):
    def test_accepts_complete_transport_terminal_records(self) -> None:
        for route in ("direct", "relay"):
            with self.subTest(route=route):
                output = f"libwebrtc diagnostic\n{transport_record(route)}\n"
                candidate = "relay" if route == "relay" else "host"
                self.assertEqual(
                    validate_peer_output(output, mode=route, slice_name="transport"),
                    f"{route}(local={candidate},remote={candidate},protocol=udp)",
                )

    def test_accepts_complete_product_terminal_records(self) -> None:
        for route in ("direct", "relay"):
            with self.subTest(route=route):
                output = f"libwebrtc diagnostic\n{product_record(route)}\n"
                candidate = "relay" if route == "relay" else "host"
                self.assertEqual(
                    validate_peer_output(output, mode=route, slice_name="product"),
                    f"{route}(local={candidate},remote={candidate},protocol=udp)",
                )

    def test_rejects_relay_label_with_host_candidates(self) -> None:
        fake_transport = transport_record("relay").replace(
            "local=relay,remote=relay", "local=host,remote=host"
        )
        fake_product = product_record("relay").replace(
            "local=relay,remote=relay", "local=host,remote=host"
        )
        for output, slice_name in (
            (fake_transport, "transport"),
            (fake_product, "product"),
        ):
            with self.subTest(slice=slice_name):
                with self.assertRaisesRegex(E2EFailure, "relay candidate types"):
                    validate_peer_output(output, mode="relay", slice_name=slice_name)

    def test_rejects_false_e2ee_with_true_text_in_unknown_suffix(self) -> None:
        output = (
            product_record(application_e2ee="false")
            + " note=applicationE2EE=true-not-proven"
        )
        with self.assertRaisesRegex(E2EFailure, "malformed or untrusted"):
            validate_peer_output(output, mode="direct", slice_name="product")

    def test_rejects_fail_record_followed_by_stale_pass_suffix(self) -> None:
        output = "\n".join((
            "Phase 3 product signaling self-test: FAIL (actual failure)",
            "Phase 3 product signaling self-test: PASS-STALE "
            "productSession=true protocolV1=true route=direct epoch=1 "
            "configEpoch=2 rotation=90 mediaSource=videotoolbox-hevc "
            "keyframe=true delta=true input=true "
            "applicationE2EE=true-old "
            "selectedCandidatePair=direct(local=host,remote=host,protocol=udp)",
        ))
        with self.assertRaisesRegex(E2EFailure, "exactly one"):
            validate_peer_output(output, mode="direct", slice_name="product")

    def test_rejects_pass_and_fail_terminal_records(self) -> None:
        output = "\n".join((
            "Phase 3 product signaling self-test: FAIL (actual failure)",
            product_record(),
        ))
        with self.assertRaisesRegex(E2EFailure, "exactly one"):
            validate_peer_output(output, mode="direct", slice_name="product")

    def test_rejects_duplicate_or_conflicting_pass_terminal_records(self) -> None:
        for second in (product_record(), product_record("relay")):
            with self.subTest(second=second):
                with self.assertRaisesRegex(E2EFailure, "exactly one"):
                    validate_peer_output(
                        f"{product_record()}\n{second}",
                        mode="direct",
                        slice_name="product",
                    )

    def test_rejects_unknown_terminal_field_or_status_suffix(self) -> None:
        outputs = (
            product_record()[:-1] + ", note=stale)",
            product_record().replace(": PASS ", ": PASS-STALE "),
        )
        for output in outputs:
            with self.subTest(output=output):
                with self.assertRaisesRegex(E2EFailure, "malformed or untrusted"):
                    validate_peer_output(output, mode="direct", slice_name="product")

    def test_rejects_fields_spliced_across_lines(self) -> None:
        output = product_record().replace(
            "input=true, applicationE2EE=true, ",
            "input=true,\napplicationE2EE=true, ",
        )
        with self.assertRaisesRegex(E2EFailure, "malformed or untrusted"):
            validate_peer_output(output, mode="direct", slice_name="product")

    def test_rejects_evidence_split_across_untrusted_log_lines(self) -> None:
        output = (
            product_record().replace("applicationE2EE=true, ", "")
            + "\nnote applicationE2EE=true"
        )
        with self.assertRaisesRegex(E2EFailure, "malformed or untrusted"):
            validate_peer_output(output, mode="direct", slice_name="product")

    def test_rejects_false_transport_e2ee_with_true_suffix(self) -> None:
        output = transport_record().replace(
            "applicationE2EE=true, ",
            "applicationE2EE=false, ",
        ) + " applicationE2EE=true-old"
        with self.assertRaisesRegex(E2EFailure, "malformed or untrusted"):
            validate_peer_output(output, mode="direct", slice_name="transport")

    def test_rejects_unknown_slice_without_reusing_product_parser(self) -> None:
        with self.assertRaisesRegex(E2EFailure, "unsupported Phase 3 peer slice"):
            validate_peer_output(
                product_record(),
                mode="direct",
                slice_name="unknown",
            )


if __name__ == "__main__":
    unittest.main()
