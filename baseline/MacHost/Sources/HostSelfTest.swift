import CoreGraphics
import Foundation

enum HostSelfTest {
    static func run() -> Bool {
        var failures: [String] = []

        let mapped = WindowPlacement.mappedFrame(
            CGRect(x: 100, y: 100, width: 800, height: 600),
            from: CGRect(x: 0, y: 0, width: 1920, height: 1080),
            to: CGRect(x: 1920, y: 0, width: 1200, height: 800)
        )
        if mapped.minX < 1920 || mapped.maxX > 3120 ||
            mapped.minY < 0 || mapped.maxY > 800 {
            failures.append("mapped window escaped target display")
        }

        let oversized = WindowPlacement.mappedFrame(
            CGRect(x: 0, y: 0, width: 3000, height: 2000),
            from: CGRect(x: 0, y: 0, width: 1920, height: 1080),
            to: CGRect(x: -1200, y: 0, width: 1200, height: 800)
        )
        if oversized != CGRect(x: -1200, y: 0, width: 1200, height: 800) {
            failures.append("oversized window was not clamped to target display")
        }

        let recovered = WindowPlacement.recoveryFrame(
            CGRect(x: -1100, y: 100, width: 600, height: 400),
            originalDisplayBounds: CGRect(x: -1200, y: 0, width: 1200, height: 800),
            originalDisplayUUID: "offline",
            onlineDisplays: [DisplayRecoveryTarget(
                persistentUUID: "main",
                bounds: CGRect(x: 0, y: 0, width: 1920, height: 1080)
            )],
            mainDisplayBounds: CGRect(x: 0, y: 0, width: 1920, height: 1080)
        )
        if !CGRect(x: 0, y: 0, width: 1920, height: 1080).contains(recovered) {
            failures.append("offline-display window was not recovered to main")
        }

        let mappedInput = StreamInputMapper.point(
            normalizedX: 0.25,
            normalizedY: 0.75,
            in: CGRect(x: -1920, y: -100, width: 1920, height: 1080)
        )
        if mappedInput != CGPoint(x: -1440, y: 710) ||
            StreamInputMapper.point(
                normalizedX: .nan,
                normalizedY: 0.5,
                in: CGRect(x: 0, y: 0, width: 100, height: 100)
            ) != nil {
            failures.append("normalized input validation or mapping failed")
        }

        if HostStartupPolicy.shouldRecover(
            autoStartEnabled: true,
            hasScreenRecordingPermission: true,
            hasCompletedOnboarding: true,
            explicitHeadlessBenchmark: false,
            isUnattendedOperation: false
        ) {
            failures.append("interactive operation was eligible for unattended recovery")
        }

        let hiDPIIdentity = VirtualDisplayIdentity.productID(
            logicalWidth: 2000,
            logicalHeight: 1200,
            physicalWidth: 4000,
            physicalHeight: 2400,
            refreshRate: 60,
            hiDPI: true
        )
        let nativeIdentity = VirtualDisplayIdentity.productID(
            logicalWidth: 4000,
            logicalHeight: 2400,
            physicalWidth: 4000,
            physicalHeight: 2400,
            refreshRate: 60,
            hiDPI: false
        )
        if hiDPIIdentity == nativeIdentity {
            failures.append("HiDPI and native virtual display identities collided")
        }

        let expectedDelays: [TimeInterval?] = [
            nil,
            1,
            2,
            4,
            8,
            16,
            30,
            30,
            30,
            nil
        ]
        let actualDelays = (-1...UnattendedRecoveryPolicy.maximumAttempts).map {
            UnattendedRecoveryPolicy.delay(afterFailure: $0)
        }
        if actualDelays != expectedDelays {
            failures.append("unattended recovery backoff differs from policy")
        }

        let callbackGeneration = ClientCallbackGenerationGate()
        callbackGeneration.advance(to: 1)
        callbackGeneration.advance(to: 2)
        var callbackMutations = 0
        if callbackGeneration.performIfCurrent(1, operation: {
            callbackMutations += 1
        }) || callbackMutations != 0 {
            failures.append("stale client callback survived authoritative takeover")
        }
        if !callbackGeneration.performIfCurrent(2, operation: {
            callbackMutations += 1
        }) || callbackMutations != 1 {
            failures.append("current client callback was rejected")
        }
        callbackGeneration.advance(to: 1)
        if !callbackGeneration.isCurrent(2) {
            failures.append("client callback generation rolled back")
        }

        if FallbackStoppedPolicy.action(
            followsMainDisplay: true,
            capturedDisplayID: 10,
            currentMainDisplayID: 11
        ) != .rebuild(11) {
            failures.append("stopped main-display fallback missed replacement")
        }

        if ADBDeviceSelectionPolicy.resolveTargetSerial(
            configuredSerial: "target",
            connectedSerials: ["other", "target"]
        ) != "target" {
            failures.append("ADB selection ignored the configured online device")
        }
        if ADBDeviceSelectionPolicy.resolveTargetSerial(
            configuredSerial: "target",
            connectedSerials: ["other"]
        ) != nil {
            failures.append("ADB selection fell back from an offline configured device")
        }
        if ADBDeviceSelectionPolicy.resolveTargetSerial(
            configuredSerial: "",
            connectedSerials: ["only"]
        ) != "only" {
            failures.append("ADB selection did not use the only unconfigured device")
        }
        if ADBDeviceSelectionPolicy.resolveTargetSerial(
            configuredSerial: "",
            connectedSerials: ["first", "second"]
        ) != nil {
            failures.append("ADB selection chose an arbitrary unconfigured device")
        }

        let displays = DisplayCatalog.onlineDisplays()
        if displays.isEmpty {
            failures.append("online display catalog is empty")
        }
        if DisplayCatalog.resolve(CGDirectDisplayID.max) != CGMainDisplayID() {
            failures.append("missing display did not fall back to main display")
        }
        let fakeDisplays = [
            HostDisplayDescriptor(
                id: 10,
                persistentUUID: "main",
                name: "Main",
                width: 100,
                height: 100,
                isMain: true
            ),
            HostDisplayDescriptor(
                id: 11,
                persistentUUID: "secondary",
                name: "Secondary",
                width: 100,
                height: 100,
                isMain: false
            )
        ]
        if DisplayCatalog.resolve(
            persistentUUID: "missing",
            fallbackID: 11,
            onlineDisplays: fakeDisplays,
            mainDisplayID: 10
        ) != 10 {
            failures.append("missing UUID reused a potentially stale display ID")
        }
        if DisplayCatalog.resolve(
            persistentUUID: "secondary",
            fallbackID: 10,
            onlineDisplays: fakeDisplays,
            mainDisplayID: 10
        ) != 11 {
            failures.append("display UUID did not resolve its current ID")
        }
        if ScreenCapture.ShareableDisplayReadiness.evaluate(
            shareableDisplayIDs: [],
            requestedDisplayID: 10,
            followsMainDisplay: true,
            currentMainDisplayID: 10,
            currentMainPixelSize: (width: 1920, height: 1080)
        ) != .fallbackToCurrentMain {
            failures.append("empty ScreenCaptureKit catalog did not fall back to current-main capture")
        }
        if ScreenCapture.ShareableDisplayReadiness.evaluate(
            shareableDisplayIDs: [],
            requestedDisplayID: 10,
            followsMainDisplay: true,
            currentMainDisplayID: 0,
            currentMainPixelSize: (width: 0, height: 0)
        ) != .unavailable(
            "ScreenCaptureKit returned no capturable displays, and CoreGraphics does not expose a usable current main display. Unlock the Mac session and attach a physical, dummy, or Screen Sharing display."
        ) {
            failures.append("empty ScreenCaptureKit catalog did not fail closed without a usable main display")
        }
        if ScreenCapture.ShareableDisplayReadiness.evaluate(
            shareableDisplayIDs: [],
            requestedDisplayID: 10,
            followsMainDisplay: false,
            currentMainDisplayID: 10,
            currentMainPixelSize: (width: 1920, height: 1080)
        ) != .unavailable(
            "ScreenCaptureKit returned no capturable displays. Unlock the Mac session and attach a physical, dummy, or Screen Sharing display."
        ) {
            failures.append("empty ScreenCaptureKit catalog did not fail closed for non-main capture")
        }
        if ScreenCapture.MissingConfiguredStreamReadiness.evaluate(
            followsMainDisplay: true
        ) != .fallbackToCurrentMain {
            failures.append("missing configured SCStream did not fall back for current-main capture")
        }
        if ScreenCapture.MissingConfiguredStreamReadiness.evaluate(
            followsMainDisplay: false
        ) != .unavailable("Capture stream was not configured.") {
            failures.append("missing configured SCStream did not fail closed for non-main capture")
        }
        for display in displays {
            let mode = CGDisplayCopyDisplayMode(display.id)
            print(
                "Host display evidence: id=\(display.id), " +
                "uuid=\(display.persistentUUID ?? "unavailable"), " +
                "logical=\(display.width)x\(display.height), " +
                "physical=\(mode?.pixelWidth ?? 0)x\(mode?.pixelHeight ?? 0)"
            )
        }
        let privateDisplayCapability = VirtualDisplayPrivateAPICapability.evaluate()
        print(
            "Private virtual display API shape check: " +
            (privateDisplayCapability.isAvailable ? "available" : "unavailable") +
            " (class/selector presence is not creation/capture evidence)"
        )

        if failures.isEmpty {
            print(
                "Host self-test: PASS (display identity/catalog, input/window " +
                "geometry, startup/recovery policy, callback generation, " +
                "fallback replacement, ADB device selection)"
            )
            return true
        }
        print("Host self-test: FAIL (\(failures.joined(separator: "; ")))")
        return false
    }
}
