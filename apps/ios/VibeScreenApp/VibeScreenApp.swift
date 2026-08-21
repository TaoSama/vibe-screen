import SwiftUI

@main
struct VibeScreenApp: App {
    @StateObject private var model = StreamViewModel()
    @State private var audioSelfTestResult: String?

    var body: some Scene {
        WindowGroup {
            ContentView(model: model)
                .overlay(alignment: .top) {
                    if let audioSelfTestResult {
                        Text(audioSelfTestResult)
                            .font(.footnote.monospaced())
                            .padding(10)
                            .background(.regularMaterial)
                            .accessibilityIdentifier("audio-playback-self-test-result")
                    }
                }
                .task {
                    guard ProcessInfo.processInfo.arguments.contains("--audio-playback-self-test"),
                          audioSelfTestResult == nil else { return }
                    do {
                        let snapshot = try await AudioPlaybackSelfTest.run()
                        audioSelfTestResult = [
                            "AUDIO_PLAYBACK_SELF_TEST=PASS",
                            "scheduled=\(snapshot.scheduledBufferTotal)",
                            "played=\(snapshot.playedBufferTotal)",
                            "queued=\(snapshot.scheduledBufferCount)",
                            "queue_empty=\(snapshot.queueEmptyCount)",
                            "late_completions=\(snapshot.lateCompletionCount)",
                            "overruns=\(snapshot.overrunDropCount)",
                            "stops=\(snapshot.stopCount)",
                        ].joined(separator: " ")
                    } catch {
                        audioSelfTestResult = "AUDIO_PLAYBACK_SELF_TEST=FAIL error=\(error.localizedDescription)"
                    }
                }
        }
    }
}
