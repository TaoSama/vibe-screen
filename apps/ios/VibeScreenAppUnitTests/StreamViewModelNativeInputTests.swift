import Foundation
import XCTest
@testable import VibeScreen
import VibeScreenCore
import VibeScreenProtocol

private enum KeyEventRecorderError: Error {
    case timedOut
}

private final class KeyEventRecorder: @unchecked Sendable {
    private let lock = NSLock()
    private var events: [VSKeyEvent] = []

    func append(_ event: VSKeyEvent) {
        lock.withLock { events.append(event) }
    }

    func firstRelease(usbHIDUsage: UInt32) -> VSKeyEvent? {
        lock.withLock {
            events.first { $0.usbHidUsage == usbHIDUsage && !$0.pressed }
        }
    }

    var releaseEvents: [VSKeyEvent] {
        lock.withLock { events.filter { !$0.pressed } }
    }

    func waitForFirstRelease(usbHIDUsage: UInt32) async throws -> VSKeyEvent {
        for _ in 0..<50 {
            if let event = firstRelease(usbHIDUsage: usbHIDUsage) { return event }
            try await Task.sleep(nanoseconds: 10_000_000)
        }
        XCTFail("Timed out waiting for key release envelope")
        throw KeyEventRecorderError.timedOut
    }
}

@MainActor
final class StreamViewModelNativeInputTests: XCTestCase {
    func testKeyReleaseUsesCurrentModifierMaskNotPressTimeStaleMask() async throws {
        let viewModel = makeStreamingViewModel()
        let recorder = attachRecorder(to: viewModel)

        let shiftUsage: UInt32 = 0xE1
        let aUsage: UInt32 = 0x04
        let shiftMask = USBHIDModifierWire.leftShift

        XCTAssertTrue(viewModel.sendKey(
            usbHIDUsage: shiftUsage,
            pressed: true,
            standardModifierMask: shiftMask,
            text: ""
        ))
        XCTAssertTrue(viewModel.sendKey(
            usbHIDUsage: aUsage,
            pressed: true,
            standardModifierMask: shiftMask,
            text: "a"
        ))
        XCTAssertTrue(viewModel.sendKey(
            usbHIDUsage: shiftUsage,
            pressed: false,
            standardModifierMask: 0,
            text: ""
        ))
        XCTAssertTrue(viewModel.sendKey(
            usbHIDUsage: aUsage,
            pressed: false,
            standardModifierMask: 0,
            text: ""
        ))

        let aRelease = try await recorder.waitForFirstRelease(usbHIDUsage: aUsage)
        XCTAssertEqual(aRelease.modifierMask, 0)
    }

    func testReleaseActiveInputClearsKeysWithZeroModifierMask() async throws {
        let viewModel = makeStreamingViewModel()
        let recorder = attachRecorder(to: viewModel)

        let shiftUsage: UInt32 = 0xE1
        let aUsage: UInt32 = 0x04
        let shiftMask = USBHIDModifierWire.leftShift

        XCTAssertTrue(viewModel.sendKey(
            usbHIDUsage: shiftUsage,
            pressed: true,
            standardModifierMask: shiftMask,
            text: ""
        ))
        XCTAssertTrue(viewModel.sendKey(
            usbHIDUsage: aUsage,
            pressed: true,
            standardModifierMask: shiftMask,
            text: "a"
        ))

        let batch = viewModel.releaseActiveInput()

        XCTAssertTrue(batch.allAdmitted)
        try await batch.waitForAdmittedReleases()
        XCTAssertEqual(recorder.releaseEvents.map(\.modifierMask), [0, 0])
    }
    private func makeStreamingViewModel() -> StreamViewModel {
        let viewModel = StreamViewModel()
        viewModel.isStreaming = true
        viewModel.negotiatedCapabilities = [.keyboard, .usbHidModifierByte]
        viewModel.selectedStreamID = 1

        let owner = SessionOwner(connectionOwner: ConnectionOwner())
        viewModel.sessionOwner = owner
        viewModel.decoderOwners[1] = DecoderOwner(
            sessionOwner: owner,
            streamID: 1,
            configEpoch: 0
        )
        viewModel.displayBindings = [DisplayStreamBinding(displayID: "display-1", streamID: 1)]
        return viewModel
    }

    private func attachRecorder(to viewModel: StreamViewModel) -> KeyEventRecorder {
        let recorder = KeyEventRecorder()
        let outbox = ControlOutbox(
            sender: { _, frame, _ in
                let envelope = try EnvelopeCodec.deserialize(frame.payload)
                if envelope.hasKeyEvent { recorder.append(envelope.keyEvent) }
            },
            onFailure: { _ in }
        )
        outbox.activate(owner: viewModel.sessionOwner!)
        viewModel.controlOutbox = outbox
        return recorder
    }
}
