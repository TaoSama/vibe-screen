import CoreGraphics
import XCTest
@testable import Telemachus

final class StreamInputInjectorKeyReleaseTests: XCTestCase {
    func testPressedKeyStateConsumesKeysByHIDUsageAndIsIdempotent() {
        var state = PressedKeyState()

        state.didPost(usbHIDUsage: 0x05, pressed: true, modifierMask: 2)
        state.didPost(usbHIDUsage: 0x04, pressed: true, modifierMask: 1)
        state.didPost(usbHIDUsage: 0x05, pressed: true, modifierMask: 3)

        XCTAssertEqual(
            state.consumeResetKeys(),
            [
                .init(usbHIDUsage: 0x04, modifierMask: 1),
                .init(usbHIDUsage: 0x05, modifierMask: 3),
            ]
        )
        XCTAssertEqual(state.consumeResetKeys(), [])
    }

    func testPostedKeyUpRemovesKeyFromResetState() {
        var state = PressedKeyState()

        state.didPost(usbHIDUsage: 0x04, pressed: true, modifierMask: 1)
        state.didPost(usbHIDUsage: 0x04, pressed: false, modifierMask: 0)

        XCTAssertEqual(state.consumeResetKeys(), [])
    }

    func testInjectorResetReleasesOnlyHeldKeysInStableOrder() throws {
        var posted: [CGEvent] = []
        let injector = StreamInputInjector(
            eventSource: try XCTUnwrap(CGEventSource(stateID: .privateState)),
            keyboardEventPoster: { posted.append($0.copy()!) }
        )

        XCTAssertTrue(injector.handleKey(
            usbHIDUsage: 0x05,
            pressed: true,
            modifierMask: StreamInputWire.modifierCommand
        ))
        XCTAssertTrue(injector.handleKey(
            usbHIDUsage: 0x04,
            pressed: true,
            modifierMask: StreamInputWire.modifierShift
        ))
        XCTAssertTrue(injector.handleKey(
            usbHIDUsage: 0x05,
            pressed: false,
            modifierMask: StreamInputWire.modifierCommand
        ))

        injector.reset()

        XCTAssertEqual(posted.map(\.type), [.keyDown, .keyDown, .keyUp, .keyUp])
        XCTAssertEqual(
            posted.map { $0.getIntegerValueField(.keyboardEventKeycode) },
            [11, 0, 11, 0]
        )
        XCTAssertTrue(posted[3].flags.contains(.maskShift))

        injector.reset()
        XCTAssertEqual(posted.count, 4)
    }

    func testUnsupportedKeyIsNeverTrackedForReset() throws {
        var posted: [CGEvent] = []
        let injector = StreamInputInjector(
            eventSource: try XCTUnwrap(CGEventSource(stateID: .privateState)),
            keyboardEventPoster: { posted.append($0.copy()!) }
        )

        XCTAssertFalse(injector.handleKey(
            usbHIDUsage: UInt32.max,
            pressed: true,
            modifierMask: 0
        ))
        injector.reset()

        XCTAssertTrue(posted.isEmpty)
    }

    func testTakeoverCancellationReleasesHeldKeyForCurrentGeneration() throws {
        var posted: [CGEvent] = []
        let injector = StreamInputInjector(
            eventSource: try XCTUnwrap(CGEventSource(stateID: .privateState)),
            keyboardEventPoster: { posted.append($0.copy()!) }
        )
        XCTAssertTrue(injector.handleKey(
            usbHIDUsage: 0x04,
            pressed: true,
            modifierMask: StreamInputWire.modifierCommand
        ))

        let server = StreamingServer(port: 0)
        let released = expectation(description: "takeover releases held key")
        server.onInputCancelled = { generation in
            XCTAssertEqual(generation, 2)
            injector.reset()
            released.fulfill()
        }
        server.advanceClientGenerationForSelfTest(to: 2)
        server.dispatchTakeoverInputCancellation(
            oldConnectionWasPresent: true,
            generation: 2
        )

        wait(for: [released], timeout: 1)
        XCTAssertEqual(posted.map(\.type), [.keyDown, .keyUp])
        XCTAssertTrue(posted[1].flags.contains(.maskCommand))
    }
}
