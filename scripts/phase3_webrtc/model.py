"""Shared constants and errors for the Phase 3 local E2E."""

DEFAULT_TIMEOUT_SECONDS = 45
DEFAULT_SESSION_TTL_SECONDS = 120
SIGNALING_VERSION = "0.1.0"
BUILD_MANIFEST_SCHEMA = "dev.vibescreen.phase3-webrtc-build/v1"
BUILD_MANIFEST_NAME = "build-manifest.json"
EVIDENCE_SCHEMA = "dev.vibescreen.phase3-webrtc-e2e/v1"
PUBLIC_EVIDENCE_SCHEMA = "dev.vibescreen.phase3-public-e2e/v1"
PUBLIC_DIAGNOSTIC_SCHEMA = "dev.vibescreen.phase3-public-diagnostic/v1"
PUBLIC_GATE_FAILURE_SCHEMA = "dev.vibescreen.phase3-gate-failure/v1"
GENERATED_SOURCE_PATH_PREFIXES = ("scripts/phase3_webrtc/.build/",)
SUPPORTED_COTURN_VERSIONS = ("4.16.0", "4.17.0")
SUPPORTED_CANDIDATE_PROTOCOLS = ("udp", "tcp", "tls")
SUPPORTED_CANDIDATE_TYPES = ("host", "srflx", "prflx", "relay")
SLICE_CONFIGURATION = {
    "transport": {
        "command": "--phase3-webrtc-signaling-self-test",
        "pass_marker": "Phase 3 WebRTC signaling self-test: PASS",
    },
    "product": {
        "command": "--phase3-product-signaling-self-test",
        "pass_marker": "Phase 3 product signaling self-test: PASS",
    },
}
PRODUCT_PLAINTEXT_SEEDS = (
    "VIBE-PRODUCT-E2E-KEYFRAME-PLAINTEXT-SEED",
    "VIBE-PRODUCT-E2E-DELTA-PLAINTEXT-SEED",
)
RELAY_HOOK_ENVIRONMENT = (
    "VIBE_WEBRTC_ICE_URLS",
    "VIBE_WEBRTC_ICE_USERNAME",
    "VIBE_WEBRTC_ICE_CREDENTIAL",
    "VIBE_WEBRTC_FORCE_RELAY",
)
COTURN_LEGACY_RESIDUE_PATTERNS = (
    "/var/tmp/turn_*.log",
    "/var/tmp/turn_*.pid",
    "/var/tmp/turnserver.pid",
)


class E2EFailure(RuntimeError):
    """An evidence or privacy gate failed."""
