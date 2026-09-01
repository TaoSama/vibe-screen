import Combine
import XCTest
@testable import Telemachus

/// Offline coverage for the live-telemetry model that was split out of the
/// SwiftUI `DisplaySettings` root so per-second FPS/bitrate updates no longer
/// re-evaluate a SwiftUI body. The de-duplicating publisher is the behavioral
/// contract the AppKit bridge relies on.
final class StreamMetricsTests: XCTestCase {
    private static let highFrequencyUpdateCount = 10_000
    private var cancellables: Set<AnyCancellable> = []

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    func testStartsAtZero() {
        let metrics = StreamMetrics()
        XCTAssertEqual(metrics.fps.value, 0)
        XCTAssertEqual(metrics.bitrateMbps.value, 0)
    }

    func testStreamStatsTelemetryIncludesFrameLifecycleSnapshot() {
        let attributes = StreamStatsTelemetryBuilder.attributes(
            fps: 60,
            mbps: 24,
            averageFrameAgeMs: 4.5,
            droppedFrames: 2,
            queueDepth: 1,
            queueCapacity: 2,
            encoderStats: (inFlight: 1, capacity: 2, frameRegistryCount: 1),
            frameLifecycleStats: StreamFrameLifecycleStats(
                latestPixelBufferRetained: 1,
                latestPixelBufferCapacity: 1,
                fallbackCaptureActive: true,
                encoderPresent: true
            )
        )

        XCTAssertEqual(attributes["queue_depth"], .integer(1))
        XCTAssertEqual(attributes["queue_capacity"], .integer(2))
        XCTAssertEqual(attributes["encoder_in_flight"], .integer(1))
        XCTAssertEqual(attributes["encoder_in_flight_capacity"], .integer(2))
        XCTAssertEqual(attributes["frame_registry_count"], .integer(1))
        XCTAssertEqual(attributes["latest_pixel_buffer_retained"], .integer(1))
        XCTAssertEqual(attributes["latest_pixel_buffer_capacity"], .integer(1))
        XCTAssertEqual(attributes["fallback_capture_active"], .boolean(true))
        XCTAssertEqual(attributes["encoder_present"], .boolean(true))
    }

    func testUpdateStoresLatestValues() {
        let metrics = StreamMetrics()
        metrics.update(fps: 59.9, bitrateMbps: 34.2)
        XCTAssertEqual(metrics.fps.value, 59.9, accuracy: 0.0001)
        XCTAssertEqual(metrics.bitrateMbps.value, 34.2, accuracy: 0.0001)
    }

    func testUnchangedValuesDoNotEmitAfterSubscription() {
        let metrics = StreamMetrics()
        metrics.update(fps: 60, bitrateMbps: 35)

        // CurrentValueSubject replays its current value once on subscribe; count
        // only the emissions that arrive after that initial replay.
        var fpsEmissions = 0
        var bitrateEmissions = 0
        var seenInitialFPS = false
        var seenInitialBitrate = false
        metrics.fps
            .sink { _ in
                if seenInitialFPS { fpsEmissions += 1 } else { seenInitialFPS = true }
            }
            .store(in: &cancellables)
        metrics.bitrateMbps
            .sink { _ in
                if seenInitialBitrate { bitrateEmissions += 1 } else { seenInitialBitrate = true }
            }
            .store(in: &cancellables)

        // Re-sending the same values must not wake subscribers.
        metrics.update(fps: 60, bitrateMbps: 35)
        metrics.update(fps: 60, bitrateMbps: 35)

        XCTAssertEqual(fpsEmissions, 0)
        XCTAssertEqual(bitrateEmissions, 0)

        // A changed value emits exactly once per changed channel.
        metrics.update(fps: 59, bitrateMbps: 35)
        XCTAssertEqual(fpsEmissions, 1)
        XCTAssertEqual(bitrateEmissions, 0)

        metrics.update(fps: 59, bitrateMbps: 40)
        XCTAssertEqual(fpsEmissions, 1)
        XCTAssertEqual(bitrateEmissions, 1)
    }

    func testResetEmitsZeroOnlyWhenNonZero() {
        let metrics = StreamMetrics()
        metrics.update(fps: 60, bitrateMbps: 35)

        var fpsValues: [Double] = []
        var bitrateValues: [Double] = []
        metrics.fps.sink { fpsValues.append($0) }.store(in: &cancellables)
        metrics.bitrateMbps.sink { bitrateValues.append($0) }.store(in: &cancellables)

        metrics.reset()
        XCTAssertEqual(metrics.fps.value, 0)
        XCTAssertEqual(metrics.bitrateMbps.value, 0)
        // Initial replayed value (60/35) plus the single reset to 0.
        XCTAssertEqual(fpsValues, [60, 0])
        XCTAssertEqual(bitrateValues, [35, 0])

        // A second reset is a no-op because the values are already zero.
        metrics.reset()
        XCTAssertEqual(fpsValues, [60, 0])
        XCTAssertEqual(bitrateValues, [35, 0])
    }

    /// Isolation invariant: live-metric updates must never wake the root
    /// `DisplaySettings` SwiftUI publisher, or per-second telemetry would keep
    /// re-evaluating the settings UI body (the accumulation this change fixes).
    @MainActor
    func testMetricUpdatesDoNotTriggerSettingsObjectWillChange() {
        let settings = DisplaySettings()
        var settingsChangeCount = 0
        settings.objectWillChange
            .sink { settingsChangeCount += 1 }
            .store(in: &cancellables)

        settings.metrics.update(fps: 60, bitrateMbps: 35)
        settings.metrics.update(fps: 59.94, bitrateMbps: 34.1)
        settings.metrics.reset()
        XCTAssertEqual(
            settingsChangeCount,
            0,
            "Live metric updates must not publish through the root settings object."
        )

        // Sanity check that the subscription is wired: a real @Published write
        // does drive objectWillChange, so the zero above is meaningful.
        settings.clientConnected.toggle()
        XCTAssertEqual(settingsChangeCount, 1)
    }

    /// Regression gate for the historical Host RSS ObservationRegistrar
    /// accumulation: 10k changing FPS/bitrate samples are allowed to wake only
    /// the metric subjects, never the root `DisplaySettings` publisher observed
    /// by the SwiftUI settings tree. This checks the public ownership and
    /// publisher invariant instead of relying on private heap class names.
    @MainActor
    func testTenThousandMetricUpdatesStayOutsideRootSettingsPublisher() {
        let settings = DisplaySettings()
        let metrics = settings.metrics
        var settingsChangeCount = 0
        var fpsEmissions = 0
        var bitrateEmissions = 0
        var seenInitialFPS = false
        var seenInitialBitrate = false

        settings.objectWillChange
            .sink { settingsChangeCount += 1 }
            .store(in: &cancellables)
        metrics.fps
            .sink { _ in
                if seenInitialFPS { fpsEmissions += 1 } else { seenInitialFPS = true }
            }
            .store(in: &cancellables)
        metrics.bitrateMbps
            .sink { _ in
                if seenInitialBitrate { bitrateEmissions += 1 } else { seenInitialBitrate = true }
            }
            .store(in: &cancellables)

        for sample in 1...Self.highFrequencyUpdateCount {
            metrics.update(
                fps: 50 + Double(sample) / 100,
                bitrateMbps: 20 + Double(sample) / 10
            )
        }

        XCTAssertTrue(metrics === settings.metrics)
        XCTAssertEqual(fpsEmissions, Self.highFrequencyUpdateCount)
        XCTAssertEqual(bitrateEmissions, Self.highFrequencyUpdateCount)
        XCTAssertEqual(
            settingsChangeCount,
            0,
            "High-frequency metric samples must not publish through DisplaySettings."
        )
    }

    /// Repeated equal metric samples are intentionally no-ops. This prevents
    /// an unchanged stream-stat callback from waking the AppKit bridge, and
    /// more importantly keeps those equal samples out of the root settings
    /// publisher that SwiftUI observes.
    @MainActor
    func testTenThousandDuplicateMetricUpdatesDoNotPublish() {
        let settings = DisplaySettings()
        let metrics = settings.metrics
        metrics.update(fps: 60, bitrateMbps: 35)

        var settingsChangeCount = 0
        var fpsEmissions = 0
        var bitrateEmissions = 0
        var seenInitialFPS = false
        var seenInitialBitrate = false

        settings.objectWillChange
            .sink { settingsChangeCount += 1 }
            .store(in: &cancellables)
        metrics.fps
            .sink { _ in
                if seenInitialFPS { fpsEmissions += 1 } else { seenInitialFPS = true }
            }
            .store(in: &cancellables)
        metrics.bitrateMbps
            .sink { _ in
                if seenInitialBitrate { bitrateEmissions += 1 } else { seenInitialBitrate = true }
            }
            .store(in: &cancellables)

        for _ in 0..<Self.highFrequencyUpdateCount {
            metrics.update(fps: 60, bitrateMbps: 35)
        }

        XCTAssertEqual(fpsEmissions, 0)
        XCTAssertEqual(bitrateEmissions, 0)
        XCTAssertEqual(settingsChangeCount, 0)
    }

    /// `setIfChanged` must publish only on a real change: an equal value is a
    /// no-op (no `objectWillChange`, returns false), and a differing value
    /// writes exactly once (returns true).
    @MainActor
    func testSetIfChangedPublishesOnlyOnRealChange() {
        let settings = DisplaySettings()
        settings.adbInstalled = false

        var changeCount = 0
        settings.objectWillChange
            .sink { changeCount += 1 }
            .store(in: &cancellables)

        // Same value: no publish, reports no write.
        XCTAssertFalse(settings.setIfChanged(false, to: \.adbInstalled))
        XCTAssertEqual(changeCount, 0)

        // Changed value: exactly one publish, reports a write.
        XCTAssertTrue(settings.setIfChanged(true, to: \.adbInstalled))
        XCTAssertEqual(changeCount, 1)
        XCTAssertTrue(settings.adbInstalled)

        // Re-applying the now-current value is again a no-op.
        XCTAssertFalse(settings.setIfChanged(true, to: \.adbInstalled))
        XCTAssertEqual(changeCount, 1)
    }

    /// Periodic host-state refreshes run through `setIfChanged`; 10k unchanged
    /// refresh samples must not produce 10k root-object publishes or build up a
    /// fresh SwiftUI observation graph for every timer tick.
    @MainActor
    func testTenThousandUnchangedHostStateRefreshesDoNotPublish() {
        let settings = DisplaySettings()
        let displays = [
            HostDisplayDescriptor(
                id: 2,
                persistentUUID: "display-b",
                name: "Display B",
                width: 1920,
                height: 1080,
                isMain: false
            ),
            HostDisplayDescriptor(
                id: 1,
                persistentUUID: "display-a",
                name: "Display A",
                width: 2560,
                height: 1440,
                isMain: true
            )
        ]
        let stableDisplays = DisplayCatalog.sortedByStableOrder(displays)
        settings.adbInstalled = true
        settings.hasScreenRecordingPermission = true
        settings.hasAccessibilityPermission = false
        settings.usbDeviceConnected = false
        settings.availableADBDevices = []
        settings.adbReverseConfigured = false
        settings.wifiConnected = true
        settings.listeningAddress = "192.0.2.10"
        settings.availableDisplays = stableDisplays

        var changeCount = 0
        settings.objectWillChange
            .sink { changeCount += 1 }
            .store(in: &cancellables)

        var writes = 0
        for _ in 0..<Self.highFrequencyUpdateCount {
            writes += settings.setIfChanged(true, to: \.adbInstalled) ? 1 : 0
            writes += settings.setIfChanged(true, to: \.hasScreenRecordingPermission) ? 1 : 0
            writes += settings.setIfChanged(false, to: \.hasAccessibilityPermission) ? 1 : 0
            writes += settings.setIfChanged(false, to: \.usbDeviceConnected) ? 1 : 0
            writes += settings.setIfChanged([], to: \.availableADBDevices) ? 1 : 0
            writes += settings.setIfChanged(false, to: \.adbReverseConfigured) ? 1 : 0
            writes += settings.setIfChanged(true, to: \.wifiConnected) ? 1 : 0
            writes += settings.setIfChanged("192.0.2.10", to: \.listeningAddress) ? 1 : 0
            writes += settings.setIfChanged(stableDisplays, to: \.availableDisplays) ? 1 : 0
        }

        XCTAssertEqual(writes, 0)
        XCTAssertEqual(
            changeCount,
            0,
            "Unchanged periodic host-state samples must not publish through DisplaySettings."
        )
    }

    /// When a periodic host-state value really changes, publication should be
    /// proportional to the number of real writes only. This catches accidental
    /// extra root publishes on the changing path without depending on private
    /// SwiftUI observation internals.
    @MainActor
    func testTenThousandChangingHostStateRefreshesPublishOncePerWrite() {
        let settings = DisplaySettings()
        settings.adbInstalled = false

        var changeCount = 0
        settings.objectWillChange
            .sink { changeCount += 1 }
            .store(in: &cancellables)

        var writes = 0
        for sample in 0..<Self.highFrequencyUpdateCount {
            let nextValue = sample.isMultiple(of: 2)
            writes += settings.setIfChanged(nextValue, to: \.adbInstalled) ? 1 : 0
        }

        XCTAssertEqual(writes, Self.highFrequencyUpdateCount)
        XCTAssertEqual(
            changeCount,
            writes,
            "Changing host-state samples must publish once per real write, with no extra root events."
        )
    }
}
