from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAC_APP_DELEGATE = ROOT / "baseline/MacHost/Sources/AppDelegate.swift"
MAC_MAIN = ROOT / "baseline/MacHost/Sources/main.swift"
MAC_SCREEN_CAPTURE = ROOT / "baseline/MacHost/Sources/ScreenCapture.swift"
MAC_ENCODED_FRAME_SINK = ROOT / "baseline/MacHost/Sources/EncodedFrameSink.swift"
MAC_INTERNET_SESSION = (
    ROOT
    / "baseline/MacHost/Sources/Phase3/ProductSession/InternetProductSession.swift"
)
MAC_REAL_MEDIA_SELF_TEST = (
    ROOT
    / "baseline/MacHost/Sources/Phase3/ProductSession/InternetProductSessionRealMediaSelfTest.swift"
)
MAKEFILE = ROOT / "Makefile"
ANDROID_MAIN_ACTIVITY = ROOT / "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/MainActivity.kt"
ANDROID_INTERNET_SESSION = (
    ROOT
    / "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/internet/InternetProductSession.kt"
)


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def compact(text: str) -> str:
    return "".join(text.split())


def require_compact(haystack: str, needle: str, *, label: str) -> None:
    if compact(needle) not in compact(haystack):
        raise AssertionError(f"missing source contract: {label}")


class Phase3RealMediaSourceContractTests(unittest.TestCase):
    def test_real_media_self_test_is_registered_in_local_self_test_target(self) -> None:
        main = source(MAC_MAIN)
        self_test = source(MAC_REAL_MEDIA_SELF_TEST)
        makefile = source(MAKEFILE)

        self.assertIn("--phase3-real-media-self-test", main)
        self.assertIn("InternetProductSessionRealMediaSelfTest.run()", main)
        self.assertIn("enum InternetProductSessionRealMediaSelfTest", self_test)
        self.assertIn("does not claim device decoder continuity", self_test)
        self.assertIn(
            '"$$host_bin" --phase3-real-media-self-test',
            makefile,
        )

    def test_macos_internet_session_is_the_screen_capture_frame_sink(self) -> None:
        encoded_sink = source(MAC_ENCODED_FRAME_SINK)
        screen_capture = source(MAC_SCREEN_CAPTURE)
        app_delegate = source(MAC_APP_DELEGATE)
        internet_session = source(MAC_INTERNET_SESSION)

        self.assertIn("protocol EncodedFrameSink: AnyObject", encoded_sink)
        self.assertIn("func sendFrame(", encoded_sink)
        self.assertIn("var currentSessionEpoch: UInt64", encoded_sink)
        self.assertIn("final class InternetProductSession: EncodedFrameSink", internet_session)

        require_compact(
            screen_capture,
            "func startStreaming(to frameSink: (any EncodedFrameSink)?",
            label="ScreenCapture.startStreaming accepts an EncodedFrameSink",
        )
        require_compact(
            screen_capture,
            """
            newEncoder.onEncodedFrame = makeEncodedFrameHandler(frameSink: frameSink)
            """,
            label="VideoToolbox encoded frames use the shared frame-sink handler",
        )
        require_compact(
            screen_capture,
            """
            self?.recordEncodedOutput(
                byteCount: data.count,
                timestamp: timestamp,
                isKeyframe: isKeyframe,
                sessionEpoch: sessionEpoch
            )
            frameSink?.sendFrame(
                data,
                timestamp: timestamp,
                isKeyframe: isKeyframe,
                sessionEpoch: sessionEpoch
            )
            """,
            label="VideoToolbox encoded frames are marked and forwarded with their session epoch",
        )
        require_compact(
            screen_capture,
            "VideoToolbox output frame media_epoch=\(sessionEpoch)",
            label="Host logs a real VideoToolbox output epoch marker",
        )

        for snippet, label in (
            (
                """
                let session = InternetProductSession()
                internetProductSession = session
                """,
                "Internet startup creates and retains the product session",
            ),
            (
                "installInternetSessionCallbacks(session, sessionToken: sessionToken)",
                "Internet startup installs product-session callbacks before streaming",
            ),
            (
                "screenCapture?.setCodec(.hevc)",
                "Internet startup selects the HEVC capture encoder",
            ),
            (
                "try session.start(configuration: configuration)",
                "Internet startup begins Protocol v1 negotiation before frame delivery",
            ),
            (
                """
                try await screenCapture?.startStreaming(
                    to: session,
                """,
                "Internet startup streams real ScreenCapture output into the product session",
            ),
        ):
            require_compact(app_delegate, snippet, label=label)

        require_compact(
            internet_session,
            """
            private func drainLatestFrame(generation: UInt64) {
                let submission = withFrameAdmissionLock
            """,
            label="InternetProductSession encodes captured frames as Protocol v1 media records",
        )
        require_compact(
            internet_session,
            """
            let frame = try codec.mediaFrame(
                payload: submission.data,
                timestamp: submission.timestamp,
                isKeyframe: submission.isKeyframe
            )
            """,
            label="InternetProductSession preserves encoded frame payload metadata",
        )
        require_compact(
            internet_session,
            """
            if case .failure(let error) = transport.sendMedia(frame) {
                fail(.transportFailure(error))
            }
            """,
            label="InternetProductSession sends encoded media through the Internet transport",
        )

    def test_android_internet_media_reaches_the_production_decoder_callback(self) -> None:
        main_activity = source(ANDROID_MAIN_ACTIVITY)
        internet_session = source(ANDROID_INTERNET_SESSION)

        require_compact(
            internet_session,
            """
            private fun handleMedia(
                owner: TransportOwner,
                payload: ByteArray,
            )
            """,
            label="Android product session decodes Internet media records into video frames",
        )
        require_compact(
            internet_session,
            """
            codec.decodeMediaFragment(payload)
            """,
            label="Android product session decodes Protocol v1 media fragments",
        )
        require_compact(
            internet_session,
            """
            frameAssembler.offer(fragment)
            """,
            label="Android product session assembles media fragments into frames",
        )
        require_compact(
            internet_session,
            """
            callbacks.onVideoFrame(frame)
            """,
            label="Android product session dispatches assembled frames",
        )
        require_compact(
            internet_session,
            """
            currentVideoConfiguration = configuration
            frameAssembler.startConfiguration(configuration, lease.authoritativeSessionEpoch)
            """,
            label="Android starts media assembly only after decoder configuration ACK",
        )

        require_compact(
            main_activity,
            "object : InternetProductSessionCallbacks {",
            label="MainActivity InternetProductSessionCallbacks implementation",
        )
        require_compact(
            main_activity,
            "videoDecoderLifecycle.onVideoConfiguration(configuration, effect, completion)",
            label="MainActivity sends Internet video configuration through the decoder lifecycle",
        )
        require_compact(
            main_activity,
            "callbackClient.onFrameReceived = frame@{",
            label="MainActivity local session receives production media frames",
        )
        require_compact(
            main_activity,
            """
            val usedDecoder =
                videoDecoderUseGate.withCurrent { dec ->
                    when (
                        val decision =
                            rendererOwner.localFrameDecision(
                                sessionCurrent = isCurrentSession(callbackClient, callbackGeneration),
                                configEpoch = configEpoch,
                                decoderAvailable = true,
                            )
                    ) {
                        RendererFramePresentationDecision.Present ->
                            dec.decode(frameData, frameSize, timestamp, isKeyframe, sessionEpoch)
                        is RendererFramePresentationDecision.Drop -> handleDrop(decision)
                    }
                    true
                } ?: false
            """,
            label="Android local video frames are renderer-admitted under the decoder use gate",
        )
        require_compact(
            main_activity,
            """
            override fun onVideoFrame(frame: ProductVideoFrame) {
                val usedDecoder =
                    videoDecoderUseGate.withCurrent { dec ->
                        when (
                            rendererOwner.internetFrameDecision(
                                sessionCurrent = isCurrentInternetSession(),
                                frameSessionEpoch = frame.sessionEpoch,
                                activeSessionEpoch = internetSessionEpoch,
                                decoderAvailable = true,
                            )
                        ) {
                            RendererFramePresentationDecision.Present ->
                                dec.decode(
                                    frame.payload,
                                    frame.payload.size,
                                    System.nanoTime(),
                                    frame.keyframe,
                                    frame.sessionEpoch,
                                )
                            is RendererFramePresentationDecision.Drop -> Unit
                        }
                        true
                    } ?: false
                if (!usedDecoder) {
                    rendererOwner.internetFrameDecision(
                        sessionCurrent = isCurrentInternetSession(),
                        frameSessionEpoch = frame.sessionEpoch,
                        activeSessionEpoch = internetSessionEpoch,
                        decoderAvailable = false,
                    )
                }
            }
            """,
            label="Android Internet video frames are renderer-admitted before production VideoDecoder",
        )


if __name__ == "__main__":
    unittest.main()
