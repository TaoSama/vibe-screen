import CoreGraphics
import XCTest
import VibeScreenProtocol
@testable import Telemachus

final class StylusEventFactoryTests: XCTestCase {
    func testTouchDragOwnerBlocksStylusUntilTouchRelease() {
        var state = PrimaryButtonOwnerState()

        XCTAssertTrue(state.beginTouchDrag())
        XCTAssertFalse(state.canHandleStylus(pointerID: 7, phase: .began))
        XCTAssertFalse(state.canHandleStylus(pointerID: 7, phase: .ended))
        XCTAssertTrue(state.endTouchDrag())
        XCTAssertTrue(state.canHandleStylus(pointerID: 7, phase: .began))
    }

    func testStylusOwnerBlocksTouchDragAndMismatchedRelease() {
        var state = PrimaryButtonOwnerState()

        XCTAssertTrue(state.canHandleStylus(pointerID: 7, phase: .began))
        state.didHandleStylus(pointerID: 7, phase: .began)
        XCTAssertFalse(state.beginTouchDrag())
        XCTAssertFalse(state.canHandleStylus(pointerID: 8, phase: .ended))
        XCTAssertTrue(state.canHandleStylus(pointerID: 7, phase: .ended))
        state.didHandleStylus(pointerID: 7, phase: .ended)
        XCTAssertTrue(state.beginTouchDrag())
    }

    func testTipStateAcceptsOnlyOneMatchingPointerSequenceAndResets() {
        var state = StylusSequenceState()

        XCTAssertFalse(state.accepts(pointerID: 7, phase: .changed, toolKind: .pen, contactState: .contact))
        XCTAssertTrue(state.accepts(pointerID: 7, phase: .began, toolKind: .pen, contactState: .contact))
        XCTAssertEqual(state.activePointerID, 7)
        XCTAssertFalse(state.accepts(pointerID: 8, phase: .began, toolKind: .pen, contactState: .contact))
        XCTAssertFalse(state.accepts(pointerID: 8, phase: .changed, toolKind: .pen, contactState: .contact))
        XCTAssertFalse(state.accepts(pointerID: 8, phase: .ended, toolKind: .pen, contactState: .contact))
        XCTAssertEqual(state.activePointerID, 7)
        XCTAssertTrue(state.accepts(pointerID: 7, phase: .changed, toolKind: .pen, contactState: .contact))
        XCTAssertEqual(state.consumeReset()?.pointerID, 7)
        XCTAssertNil(state.activePointerID)
        XCTAssertNil(state.consumeReset())

        XCTAssertTrue(state.accepts(pointerID: 9, phase: .began, toolKind: .pen, contactState: .contact))
        XCTAssertTrue(state.accepts(pointerID: 9, phase: .cancelled, toolKind: .pen, contactState: .contact))
        XCTAssertNil(state.activePointerID)
    }

    func testExtendedSequenceSeparatesHoverContactToolAndPointerIdentity() {
        var state = StylusSequenceState()
        XCTAssertTrue(state.accepts(pointerID: 3, phase: .began, toolKind: .eraser, contactState: .proximity))
        XCTAssertFalse(state.accepts(pointerID: 3, phase: .changed, toolKind: .eraser, contactState: .contact))
        XCTAssertFalse(state.accepts(pointerID: 3, phase: .changed, toolKind: .pen, contactState: .proximity))
        XCTAssertTrue(state.accepts(pointerID: 3, phase: .ended, toolKind: .eraser, contactState: .proximity))
        XCTAssertTrue(state.accepts(pointerID: 3, phase: .began, toolKind: .eraser, contactState: .contact))
        XCTAssertTrue(state.accepts(pointerID: 3, phase: .ended, toolKind: .eraser, contactState: .contact))
    }

    func testExtendedFactoryMapsHoverEraserAndBarrelFieldsWithoutMouseDown() throws {
        let factory = StylusEventFactory(
            eventSource: try XCTUnwrap(CGEventSource(stateID: .privateState))
        )
        let bounds = CGRect(x: 0, y: 0, width: 100, height: 100)
        let hover = try XCTUnwrap(factory.event(
            normalizedX: 0.5, normalizedY: 0.5, phase: .began,
            pressure: 0, tiltXDegrees: 0, tiltYDegrees: 0,
            toolKind: .eraser, buttonMask: 0b11, contactState: .proximity,
            displayBounds: bounds
        ))
        XCTAssertEqual(hover.type, .tabletProximity)
        XCTAssertEqual(hover.getIntegerValueField(.tabletProximityEventPointerType), 3)
        XCTAssertEqual(hover.getIntegerValueField(.tabletProximityEventEnterProximity), 1)
        // CoreGraphics does not retain tablet-point fields on a proximity
        // event. Barrel state is asserted below on the tablet-point contact.
        XCTAssertEqual(hover.getIntegerValueField(.tabletEventPointButtons), 0)

        let contact = try XCTUnwrap(factory.event(
            normalizedX: 0.5, normalizedY: 0.5, phase: .began,
            pressure: 0.5, tiltXDegrees: 0, tiltYDegrees: 0,
            toolKind: .pen, buttonMask: 0b01, contactState: .contact,
            displayBounds: bounds
        ))
        XCTAssertEqual(contact.type, .leftMouseDown)
        XCTAssertEqual(contact.getIntegerValueField(.tabletEventPointButtons), 0b011)
    }

    func testBuildsPressureAndNormalizedSignedTiltWithoutPosting() throws {
        let source = try XCTUnwrap(CGEventSource(stateID: .privateState))
        let factory = StylusEventFactory(eventSource: source)
        let event = try XCTUnwrap(factory.event(
            normalizedX: 0.25,
            normalizedY: 0.75,
            phase: .changed,
            pressure: 0.625,
            tiltXDegrees: 45,
            tiltYDegrees: -45,
            displayBounds: CGRect(x: -100, y: 50, width: 400, height: 200)
        ))

        XCTAssertEqual(event.type, .leftMouseDragged)
        XCTAssertEqual(event.location, CGPoint(x: 0, y: 200))
        XCTAssertEqual(event.getDoubleValueField(.tabletEventPointPressure), 0.625, accuracy: 0.0001)
        XCTAssertEqual(event.getDoubleValueField(.tabletEventTiltX), 0.5, accuracy: 0.0001)
        XCTAssertEqual(event.getDoubleValueField(.tabletEventTiltY), -0.5, accuracy: 0.0001)
    }

    func testMapsPenTipLifecycleToPrimaryMouseLifecycle() throws {
        let factory = StylusEventFactory(
            eventSource: try XCTUnwrap(CGEventSource(stateID: .privateState))
        )
        let bounds = CGRect(x: 0, y: 0, width: 100, height: 100)

        XCTAssertEqual(try XCTUnwrap(factory.event(
            normalizedX: 0.5, normalizedY: 0.5, phase: .began,
            pressure: 1, tiltXDegrees: 0, tiltYDegrees: 0,
            displayBounds: bounds
        )).type, .leftMouseDown)
        XCTAssertEqual(try XCTUnwrap(factory.event(
            normalizedX: 0.5, normalizedY: 0.5, phase: .ended,
            pressure: 0, tiltXDegrees: 0, tiltYDegrees: 0,
            displayBounds: bounds
        )).type, .leftMouseUp)
        XCTAssertEqual(try XCTUnwrap(factory.event(
            normalizedX: 0.5, normalizedY: 0.5, phase: .cancelled,
            pressure: 0, tiltXDegrees: 0, tiltYDegrees: 0,
            displayBounds: bounds
        )).type, .leftMouseUp)
    }

    func testRejectsMalformedSamplesAndImpossibleCombinedTilt() throws {
        let factory = StylusEventFactory(
            eventSource: try XCTUnwrap(CGEventSource(stateID: .privateState))
        )
        let bounds = CGRect(x: 0, y: 0, width: 100, height: 100)
        func make(
            x: Float = 0.5,
            pressure: Double = 0.5,
            tiltX: Double = 0,
            tiltY: Double = 0,
            phase: VSInputPhase = .changed
        ) -> CGEvent? {
            factory.event(
                normalizedX: x, normalizedY: 0.5, phase: phase,
                pressure: pressure, tiltXDegrees: tiltX, tiltYDegrees: tiltY,
                displayBounds: bounds
            )
        }

        XCTAssertNil(make(x: .nan))
        XCTAssertNil(make(pressure: .infinity))
        XCTAssertNil(make(pressure: -0.01))
        XCTAssertNil(make(pressure: 1.01))
        XCTAssertNil(make(tiltX: 90, tiltY: 90))
        XCTAssertNil(make(tiltX: .nan))
        XCTAssertNil(make(phase: .unspecified))
        XCTAssertNil(make(pressure: 0.1, phase: .ended))
        XCTAssertNil(make(pressure: 0.1, phase: .cancelled))
    }

    func testInjectorResetReleasesOnlyItsActiveStylusTipThroughPoster() throws {
        var posted: [CGEvent] = []
        let injector = StreamInputInjector(
            eventSource: try XCTUnwrap(CGEventSource(stateID: .privateState)),
            stylusEventPoster: { posted.append($0.copy()!) }
        )
        let bounds = CGRect(x: 10, y: 20, width: 100, height: 200)

        XCTAssertTrue(injector.handleStylus(
            pointerID: 4,
            normalizedX: 0.25,
            normalizedY: 0.5,
            phase: .began,
            pressure: 0.75,
            tiltXDegrees: 0,
            tiltYDegrees: 0,
            displayBounds: bounds
        ))
        XCTAssertFalse(injector.handleStylus(
            pointerID: 5,
            normalizedX: 0.5,
            normalizedY: 0.5,
            phase: .ended,
            pressure: 0,
            tiltXDegrees: 0,
            tiltYDegrees: 0,
            displayBounds: bounds
        ))
        XCTAssertEqual(posted.map(\.type), [.leftMouseDown])

        injector.reset()
        XCTAssertEqual(posted.map(\.type), [.leftMouseDown, .leftMouseUp])
        let release = try XCTUnwrap(posted.last)
        XCTAssertEqual(release.location, CGPoint(x: 35, y: 120))
        XCTAssertEqual(
            release.getDoubleValueField(.tabletEventPointPressure),
            0,
            accuracy: 0
        )

        injector.reset()
        XCTAssertEqual(posted.count, 2)
    }

    func testInjectorResetExitsActiveEraserProximityOnceWithoutButtons() throws {
        var posted: [CGEvent] = []
        let injector = StreamInputInjector(
            eventSource: try XCTUnwrap(CGEventSource(stateID: .privateState)),
            stylusEventPoster: { posted.append($0.copy()!) }
        )
        XCTAssertTrue(injector.handleStylus(
            pointerID: 9,
            normalizedX: 0.4,
            normalizedY: 0.6,
            phase: .began,
            pressure: 0,
            tiltXDegrees: 0,
            tiltYDegrees: 0,
            toolKind: .eraser,
            buttonMask: 0b11,
            contactState: .proximity,
            displayBounds: CGRect(x: 10, y: 20, width: 100, height: 200)
        ))
        XCTAssertEqual(posted.count, 1)
        XCTAssertEqual(posted[0].type, .tabletProximity)
        XCTAssertEqual(posted[0].getIntegerValueField(.tabletProximityEventEnterProximity), 1)

        let server = StreamingServer(port: 0)
        let released = expectation(description: "takeover exits active eraser proximity")
        server.onInputCancelled = { generation in
            XCTAssertEqual(generation, 3)
            injector.reset()
            released.fulfill()
        }
        server.advanceClientGenerationForSelfTest(to: 3)
        server.dispatchTakeoverInputCancellation(
            oldConnectionWasPresent: true,
            generation: 3
        )
        wait(for: [released], timeout: 1)

        XCTAssertEqual(posted.count, 2)
        let exit = try XCTUnwrap(posted.last)
        XCTAssertEqual(exit.type, .tabletProximity)
        XCTAssertEqual(exit.location.x, 50, accuracy: 0.001)
        XCTAssertEqual(exit.location.y, 140, accuracy: 0.001)
        XCTAssertEqual(exit.getIntegerValueField(.tabletProximityEventEnterProximity), 0)
        XCTAssertEqual(exit.getIntegerValueField(.tabletProximityEventPointerType), 3)
        XCTAssertEqual(exit.getIntegerValueField(.tabletEventPointButtons), 0)
        XCTAssertEqual(exit.getDoubleValueField(.tabletEventPointPressure), 0, accuracy: 0)

        injector.reset()
        XCTAssertEqual(posted.count, 2)
    }

    func testTakeoverCancellationReleasesActiveStylusForCurrentGeneration() throws {
        var posted: [CGEvent] = []
        let injector = StreamInputInjector(
            eventSource: try XCTUnwrap(CGEventSource(stateID: .privateState)),
            stylusEventPoster: { posted.append($0.copy()!) }
        )
        XCTAssertTrue(injector.handleStylus(
            pointerID: 4,
            normalizedX: 0.25,
            normalizedY: 0.5,
            phase: .began,
            pressure: 0.75,
            tiltXDegrees: 0,
            tiltYDegrees: 0,
            displayBounds: CGRect(x: 10, y: 20, width: 100, height: 200)
        ))
        let server = StreamingServer(port: 0)
        let released = expectation(description: "takeover releases active stylus")
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
        XCTAssertEqual(posted.map(\.type), [.leftMouseDown, .leftMouseUp])
    }
}
