import SwiftUI
import VibeScreenCore

@main
struct VibeScreenApp: App {
    private var shouldRunAudioPlaybackSelfTest: Bool {
        ProcessInfo.processInfo.arguments.contains(AudioPlaybackSelfTestDisplay.argument)
            || ProcessInfo.processInfo.environment[AudioPlaybackSelfTestDisplay.environment] == "1"
            || ProcessInfo.processInfo.environment[AudioPlaybackSelfTestDisplay.legacyEnvironment] == "1"
    }

    var body: some Scene {
        WindowGroup {
            if shouldRunAudioPlaybackSelfTest {
                AudioPlaybackSelfTestView()
            } else {
                VibeScreenRootView()
            }
        }
    }
}

private struct VibeScreenRootView: View {
    @StateObject private var model = StreamViewModel()

    var body: some View {
        ContentView(model: model)
    }
}

private struct AudioPlaybackSelfTestView: View {
    @State private var result = AudioPlaybackSelfTestDisplay.runningMessage
    @State private var hasStarted = false

    var body: some View {
        VStack(spacing: 12) {
            Text(result)
                .font(.footnote.monospaced())
                .padding(10)
                .accessibilityIdentifier(AudioPlaybackSelfTestDisplay.resultIdentifier)
                .accessibilityLabel(result)
            Button("Start audio playback self-test") {
                start()
            }
            .accessibilityIdentifier(AudioPlaybackSelfTestDisplay.startIdentifier)
            .disabled(hasStarted)
        }
        .task { await autoStartAfterFirstAccessibilityPass() }
    }

    private func autoStartAfterFirstAccessibilityPass() async {
        guard !hasStarted else { return }
        try? await Task.sleep(for: AudioPlaybackSelfTestDisplay.launchDelay)
        start()
    }

    private func start() {
        guard !hasStarted else { return }
        hasStarted = true
        Task { @MainActor in
            do {
                result = try await AudioPlaybackSelfTestDisplay.run()
            } catch {
                result = "AUDIO_PLAYBACK_SELF_TEST=FAIL error=\(error.localizedDescription)"
            }
        }
    }
}

private enum AudioPlaybackSelfTestDisplay {
    static let argument = "--audio-playback-self-test"
    static let environment = "AUDIO_PLAYBACK_SELF_TEST"
    static let legacyEnvironment = "VIBE_SCREEN_AUDIO_PLAYBACK_SELF_TEST"
    static let resultIdentifier = "audio-playback-self-test-result"
    static let startIdentifier = "audio-playback-self-test-start"
    static let runningMessage = "AUDIO_PLAYBACK_SELF_TEST=RUNNING"
    static let launchDelay: Duration = .milliseconds(500)
    private static let realAudioEnvironment = "AUDIO_PLAYBACK_SELF_TEST_REAL_AUDIO"
    private static let timeout: Duration = .seconds(15)

    static func run() async throws -> String {
        try await withThrowingTaskGroup(of: String.self) { group in
            defer { group.cancelAll() }
            group.addTask {
                let snapshot = try await audioPlaybackSnapshot()
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
                try await Task.sleep(for: timeout)
                throw AudioPlaybackSelfTestDisplayError.timedOut
            }
            guard let result = try await group.next() else {
                throw AudioPlaybackSelfTestDisplayError.timedOut
            }
            return result
        }
    }

    @MainActor
    private static func audioPlaybackSnapshot() async throws -> AudioPlaybackQueueSnapshot {
        if ProcessInfo.processInfo.environment[realAudioEnvironment] == "1" {
            return try await AudioPlaybackSelfTest.run()
        }
        return try AudioPlaybackSelfTest.runQueueOnly()
    }
}

private enum AudioPlaybackSelfTestDisplayError: Error, LocalizedError {
    case timedOut

    var errorDescription: String? {
        "音频播放自测超过 15 秒未完成"
    }
}
