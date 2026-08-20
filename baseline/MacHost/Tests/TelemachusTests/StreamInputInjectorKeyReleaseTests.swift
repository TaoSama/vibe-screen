import CoreGraphics
import XCTest
@testable import Telemachus

final class StreamInputInjectorKeyReleaseTests: XCTestCase {
    func testRightSideUSBHIDModifiersMapToCoreGraphicsFlags() {
        XCTAssertEqual(
            StreamInputMapping.modifierFlags(fromModifierMask: StreamInputWire.modifierRightControl),
            .maskControl
        )
        XCTAssertEqual(
            StreamInputMapping.modifierFlags(fromModifierMask: StreamInputWire.modifierRightShift),
            .maskShift
        )
        XCTAssertEqual(
            StreamInputMapping.modifierFlags(fromModifierMask: StreamInputWire.modifierRightOption),
            .maskAlternate
        )
        XCTAssertEqual(
            StreamInputMapping.modifierFlags(fromModifierMask: StreamInputWire.modifierRightCommand),
            .maskCommand
        )
    }

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

    func testNativePointerMoveAndPrimaryButtonLifecycleArePosted() throws {
        var posted: [CGEvent] = []
        let injector = StreamInputInjector(
            eventSource: try XCTUnwrap(CGEventSource(stateID: .privateState)),
            pointerEventPoster: { posted.append($0.copy()!) }
        )
        let bounds = CGRect(x: 100, y: 200, width: 800, height: 600)

        XCTAssertTrue(injector.handlePointer(
            normalizedX: 0.25,
            normalizedY: 0.5,
            phase: .changed,
            buttonMask: 0,
            displayBounds: bounds
        ))
        XCTAssertTrue(injector.handlePointer(
            normalizedX: 0.25,
            normalizedY: 0.5,
            phase: .began,
            buttonMask: StreamInputWire.buttonPrimary,
            displayBounds: bounds
        ))
        XCTAssertTrue(injector.handlePointer(
            normalizedX: 0.5,
            normalizedY: 0.25,
            phase: .changed,
            buttonMask: StreamInputWire.buttonPrimary,
            displayBounds: bounds
        ))
        XCTAssertTrue(injector.handlePointer(
            normalizedX: 0.5,
            normalizedY: 0.25,
            phase: .ended,
            buttonMask: 0,
            displayBounds: bounds
        ))

        XCTAssertEqual(posted.map(\.type), [.mouseMoved, .leftMouseDown, .leftMouseDragged, .leftMouseUp, .mouseMoved])
        XCTAssertEqual(posted.map { $0.getIntegerValueField(.mouseEventButtonNumber) }, [0, 0, 0, 0, 0])
        XCTAssertEqual(posted[1].getIntegerValueField(.mouseEventClickState), 1)
        XCTAssertEqual(posted[3].getIntegerValueField(.mouseEventClickState), 1)
        XCTAssertEqual(posted[0].location, CGPoint(x: 300, y: 500))
        XCTAssertEqual(posted[2].location, CGPoint(x: 500, y: 350))
    }

    func testNativePointerSecondaryButtonAndResetReleaseArePosted() throws {
        var posted: [CGEvent] = []
        let injector = StreamInputInjector(
            eventSource: try XCTUnwrap(CGEventSource(stateID: .privateState)),
            pointerEventPoster: { posted.append($0.copy()!) }
        )
        let bounds = CGRect(x: 0, y: 0, width: 400, height: 300)

        XCTAssertTrue(injector.handlePointer(
            normalizedX: 0.5,
            normalizedY: 0.5,
            phase: .began,
            buttonMask: StreamInputWire.buttonSecondary,
            displayBounds: bounds
        ))
        XCTAssertTrue(injector.handlePointer(
            normalizedX: 0.75,
            normalizedY: 0.25,
            phase: .changed,
            buttonMask: StreamInputWire.buttonSecondary,
            displayBounds: bounds
        ))

        injector.reset()
        injector.reset()

        XCTAssertEqual(posted.map(\.type), [.rightMouseDown, .rightMouseDragged, .rightMouseUp])
        XCTAssertEqual(posted.map { $0.getIntegerValueField(.mouseEventButtonNumber) }, [1, 1, 1])
        XCTAssertEqual(posted[2].location, CGPoint(x: 300, y: 75))
    }

    func testNativeScrollUsesLastPointerLocationAndIgnoresZeroDelta() throws {
        var pointerEvents: [CGEvent] = []
        var scrollEvents: [CGEvent] = []
        let injector = StreamInputInjector(
            eventSource: try XCTUnwrap(CGEventSource(stateID: .privateState)),
            pointerEventPoster: { pointerEvents.append($0.copy()!) },
            scrollEventPoster: { scrollEvents.append($0.copy()!) }
        )
        let bounds = CGRect(x: 10, y: 20, width: 100, height: 200)

        XCTAssertTrue(injector.handlePointer(
            normalizedX: 0.5,
            normalizedY: 0.25,
            phase: .changed,
            buttonMask: 0,
            displayBounds: bounds
        ))
        XCTAssertFalse(injector.handleScroll(deltaX: 0, deltaY: 0))
        XCTAssertTrue(injector.handleScroll(deltaX: 4.4, deltaY: -9.6))

        XCTAssertEqual(pointerEvents.map(\.type), [.mouseMoved])
        XCTAssertEqual(scrollEvents.map(\.type), [.scrollWheel])
        XCTAssertEqual(scrollEvents[0].location, CGPoint(x: 60, y: 70))
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
