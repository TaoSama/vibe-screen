import SwiftUI

@main
struct VibeScreenApp: App {
    private static let audioPlaybackSelfTestArgument = "--audio-playback-self-test"
    private static let audioPlaybackSelfTestRunningMessage = "AUDIO_PLAYBACK_SELF_TEST=RUNNING"
    private static let audioPlaybackSelfTestTimeout: Duration = .seconds(15)

    @StateObject private var model = StreamViewModel()
    @State private var audioSelfTestResult: String?

    private var shouldRunAudioPlaybackSelfTest: Bool {
        ProcessInfo.processInfo.arguments.contains(Self.audioPlaybackSelfTestArgument)
    }

    private static func runAudioPlaybackSelfTest() async throws -> String {
        try await withThrowingTaskGroup(of: String.self) { group in
            defer { group.cancelAll() }
            group.addTask {
                let snapshot = try await AudioPlaybackSelfTest.run()
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
            ContentView(model: model)
                .overlay(alignment: .top) {
                    if shouldRunAudioPlaybackSelfTest {
                        Text(audioSelfTestResult ?? Self.audioPlaybackSelfTestRunningMessage)
                            .font(.footnote.monospaced())
                            .padding(10)
                            .background(.regularMaterial)
                            .accessibilityIdentifier("audio-playback-self-test-result")
                    }
                }
                .task {
                    guard shouldRunAudioPlaybackSelfTest, audioSelfTestResult == nil else { return }
                    do {
                        audioSelfTestResult = try await Self.runAudioPlaybackSelfTest()
                    } catch {
                        audioSelfTestResult = "AUDIO_PLAYBACK_SELF_TEST=FAIL error=\(error.localizedDescription)"
                    }
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
