from pathlib import Path
ROOT = Path(__file__).parents[2]
ANDROID_GATE = ROOT / "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/internet/security/AdvancedChannelSecurityGate.kt"
SWIFT_GATE = ROOT / "baseline/MacHost/Sources/Phase3/Security/AdvancedChannelSecurityGate.swift"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_advanced_channel_gate_exists_on_android_and_macos() -> None:
    android = _read(ANDROID_GATE)
    swift = _read(SWIFT_GATE)

    for source in (android, swift):
        assert "AdvancedChannelOwner" in source
        assert "AdvancedChannelBinding" in source
        assert "AdvancedChannelAdmission" in source
        assert "AdvancedChannelSecurityGate" in source
        assert "sessionEpoch > 0" in source
        assert "generation > 0" in source
        assert "replaceOwner" in source
        assert "admissions.clear" in source or "admissions.removeAll" in source


def test_advanced_channel_gate_is_limited_to_audio_and_bulk_channels() -> None:
    android = _read(ANDROID_GATE)
    swift = _read(SWIFT_GATE)

    assert "override val channel = SecurityChannel.AUDIO" in android
    assert "override val channel = SecurityChannel.BULK" in android
    assert "case .audio: return .audio" in swift
    assert "case .bulk: return .bulk" in swift
    assert "SecurityChannel.CONTROL" not in android
    assert "SecurityChannel.MEDIA" not in android
    assert "case .control" not in swift
    assert "case .media" not in swift


def test_advanced_channel_gate_limits_match_record_contracts() -> None:
    android_gate = _read(ANDROID_GATE)
    swift_gate = _read(SWIFT_GATE)

    assert "InternetAudioRecordContract.MAXIMUM_PLAINTEXT_RECORD_BYTES" in android_gate
    assert "InternetBulkRecordContract.MAXIMUM_PLAINTEXT_RECORD_BYTES" in android_gate
    assert "InternetAudioRecordContract.maximumPlaintextRecordBytes" in swift_gate
    assert "InternetBulkRecordContract.maximumPlaintextRecordBytes" in swift_gate
    assert "maximumAudioBacklogBytes = 1024 * 1024" in android_gate
    assert "maximumBulkBacklogBytes = 4 * 1024 * 1024" in android_gate
    assert "maximumAudioBacklogBytes: 1024 * 1_024" in swift_gate
    assert "maximumBulkBacklogBytes: 4 * 1024 * 1024" in swift_gate
