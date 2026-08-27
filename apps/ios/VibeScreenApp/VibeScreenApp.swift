import SwiftUI
import VibeScreenCore

@main
struct VibeScreenApp: App {
    private static let audioPlaybackSelfTestArgument = "--audio-playback-self-test"
    private static let audioPlaybackSelfTestEnvironment = "AUDIO_PLAYBACK_SELF_TEST"
    private static let audioPlaybackSelfTestRealAudioEnvironment = "AUDIO_PLAYBACK_SELF_TEST_REAL_AUDIO"
    private static let audioPlaybackSelfTestRunningMessage = "AUDIO_PLAYBACK_SELF_TEST=RUNNING"
    private static let audioPlaybackSelfTestTimeout: Duration = .seconds(15)

    private var shouldRunAudioPlaybackSelfTest: Bool {
        ProcessInfo.processInfo.arguments.contains(Self.audioPlaybackSelfTestArgument)
            || ProcessInfo.processInfo.environment[Self.audioPlaybackSelfTestEnvironment] == "1"
    }

    private static func runAudioPlaybackSelfTest() async throws -> String {
        let runRealAudio = ProcessInfo.processInfo.environment[Self.audioPlaybackSelfTestRealAudioEnvironment] == "1"
        return try await withThrowingTaskGroup(of: String.self) { group in
            defer { group.cancelAll() }
            group.addTask {
                let snapshot: AudioPlaybackQueueSnapshot
                if runRealAudio {
                    snapshot = try await AudioPlaybackSelfTest.run()
                } else {
                    snapshot = try await AudioPlaybackSelfTest.runQueueOnly()
                }
                return [
                    "AUDIO_PLAYBACK_SELF_TEST=PASS",
                    "scheduled=\(snapshot.scheduledBufferTotal)",
                    "played=\(snapshot.playedBufferTotal)",
                    "queued=\(snapshot.scheduledBufferCount)",
                    "queue_empty=\(snapshot.queueEmptyCount)",
                    "late_completions=\(snapshot.lateCompletionCount)",
                    "overruns=\(snapshot.overrunDropCount)",
                    "stops=\(snapshot.stopCount)",
                ].joined(separator: " ")
            }
            group.addTask {
                try await Task.sleep(for: audioPlaybackSelfTestTimeout)
                throw AudioPlaybackSelfTestDisplayError.timedOut
            }
            guard let result = try await group.next() else {
                throw AudioPlaybackSelfTestDisplayError.timedOut
            }
            return result
        }
    }

    var body: some Scene {
        WindowGroup {
            if shouldRunAudioPlaybackSelfTest {
                AudioPlaybackSelfTestView()
            } else {
                MainAppView()
            }
        }
    }

    private struct MainAppView: View {
        @StateObject private var model = StreamViewModel()

        var body: some View {
            ContentView(model: model)
        }
    }

    private struct AudioPlaybackSelfTestView: View {
        @State private var result = VibeScreenApp.audioPlaybackSelfTestRunningMessage
        @State private var hasStarted = false

        var body: some View {
            VStack(spacing: 12) {
                Text(result)
                    .font(.footnote.monospaced())
                    .padding(10)
                    .accessibilityIdentifier("audio-playback-self-test-result")

                Button("Start audio playback self-test") {
                    guard !hasStarted else { return }
                    hasStarted = true
                    Task {
                        do {
                            result = try await VibeScreenApp.runAudioPlaybackSelfTest()
                        } catch {
                            result = "AUDIO_PLAYBACK_SELF_TEST=FAIL error=\(error.localizedDescription)"
                        }
                    }
                }
                .accessibilityIdentifier("audio-playback-self-test-start")
                .disabled(hasStarted)
            }
        }
    }
}

private enum AudioPlaybackSelfTestDisplayError: Error, LocalizedError {
    case timedOut

    var errorDescription: String? {
        "音频播放自测超过 15 秒未完成"
    }
}
