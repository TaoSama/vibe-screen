import Foundation

enum HostStartupPolicy {
    static func shouldAutoStart(
        autoStartEnabled: Bool,
        hasScreenRecordingPermission: Bool,
        hasCompletedOnboarding: Bool,
        explicitHeadlessBenchmark: Bool
    ) -> Bool {
        autoStartEnabled &&
            hasScreenRecordingPermission &&
            (hasCompletedOnboarding || explicitHeadlessBenchmark)
    }

    static func shouldRecover(
        autoStartEnabled: Bool,
        hasScreenRecordingPermission: Bool,
        hasCompletedOnboarding: Bool,
        explicitHeadlessBenchmark: Bool,
        isUnattendedOperation: Bool
    ) -> Bool {
        isUnattendedOperation && shouldAutoStart(
            autoStartEnabled: autoStartEnabled,
            hasScreenRecordingPermission: hasScreenRecordingPermission,
            hasCompletedOnboarding: hasCompletedOnboarding,
            explicitHeadlessBenchmark: explicitHeadlessBenchmark
        )
    }

    static func shouldProbeUSB(connectionMode: ConnectionMode) -> Bool {
        connectionMode == .usb
    }
}
