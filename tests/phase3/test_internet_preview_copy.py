import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
MAC_SETTINGS = ROOT / "baseline/MacHost/Sources/SettingsWindow.swift"
MAC_CONNECTION_MODE = ROOT / "baseline/MacHost/Sources/ConnectionMode.swift"
MAC_APP_DELEGATE = ROOT / "baseline/MacHost/Sources/AppDelegate.swift"
MAC_PRODUCT_CODEC = (
    ROOT
    / "baseline/MacHost/Sources/Phase3/ProductSession/InternetProductProtocolCodec.swift"
)
MAC_PROTECTED_ENGINE = (
    ROOT
    / "baseline/MacHost/Sources/Phase3/InternetTransport/ProtectedWebRTCEngine.swift"
)
ANDROID_WEBRTC_ENGINE = (
    ROOT
    / "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/internet/AndroidWebRtcPeerEngine.kt"
)
ANDROID_STRINGS = ROOT / "baseline/AndroidClient/app/src/main/res/values/strings.xml"

PROHIBITED_UI_CONCEPT_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE | re.DOTALL)
    for pattern in (
        r"\be2ee\b",
        r"\bend[\s/\u2010-\u2015-]*to[\s/\u2010-\u2015-]*end\b",
        r"\bsecure[\s\u2010-\u2015-]+internet\b",
        r"\bconnect[\s\u2010-\u2015-]+securely\b",
    )
)


def prohibited_ui_concepts(copy: str) -> list[str]:
    return [
        match.group(0)
        for pattern in PROHIBITED_UI_CONCEPT_PATTERNS
        if (match := pattern.search(copy)) is not None
    ]


def mac_user_visible_copy() -> str:
    app_delegate_lines = MAC_APP_DELEGATE.read_text(encoding="utf-8").splitlines()
    app_delegate_ui_copy = "\n".join(
        line for line in app_delegate_lines if "debugLog(" not in line
    )
    return "\n".join(
        (
            MAC_SETTINGS.read_text(encoding="utf-8"),
            MAC_CONNECTION_MODE.read_text(encoding="utf-8"),
            app_delegate_ui_copy,
            MAC_PRODUCT_CODEC.read_text(encoding="utf-8"),
            MAC_PROTECTED_ENGINE.read_text(encoding="utf-8"),
        )
    )


def android_user_visible_copy() -> str:
    return "\n".join(
        (
            ANDROID_STRINGS.read_text(encoding="utf-8"),
            ANDROID_WEBRTC_ENGINE.read_text(encoding="utf-8"),
        )
    )


class InternetPreviewCopyTests(unittest.TestCase):
    def test_user_visible_copy_preserves_preview_boundary(self) -> None:
        mac_copy = mac_user_visible_copy()
        android_copy = android_user_visible_copy()

        for copy in (mac_copy, android_copy):
            self.assertIn("development preview", copy.lower())
            self.assertIn("application records are encrypted", copy)
            self.assertIn("Public Internet traversal", copy)
            self.assertIn("real display capture", copy)
            self.assertIn("cross-service revocation", copy)
            self.assertIn("soak stability", copy)
            self.assertEqual(prohibited_ui_concepts(copy), [])

    def test_prohibited_concepts_reject_case_spacing_and_wording_variants(self) -> None:
        forbidden_variants = (
            "Secure Internet access",
            "Secure-Internet access",
            "Secure Internet-access",
            "sEcUrE   iNtErNeT session",
            "End-to-end encrypted Internet streaming",
            "End-to-end-encrypted Internet streaming",
            "End to end encrypted-Internet streaming",
            "end to end encrypted WebRTC product session",
            "E2EE is complete",
            "e2ee remains verified",
            "E2EE streaming is ready",
            "E2EE Internet-streaming remains fully production-ready",
            "E2EE streaming is fully complete",
            "Content remains end-to-end encrypted.",
            "Screen and input are E2EE.",
            "Internet streaming is fully E2EE",
            "Internet stream remains fully E2EE",
            "production-ready E2EE",
            "Both apps support Internet E2EE",
            "Connect securely",
            "End-to-end encryption is complete",
            "Internet streaming has end-to-end encryption",
            "E2EE protection is production-ready",
            "Internet streaming is end-to-end secure",
            "End / to / end encryption is verified",
            "Secure—Internet transport is ready",
        )
        for forbidden in forbidden_variants:
            with self.subTest(forbidden=forbidden):
                self.assertNotEqual(prohibited_ui_concepts(forbidden), [])


if __name__ == "__main__":
    unittest.main()
