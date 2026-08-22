import Foundation
import VibeScreenProtocol

struct GameControllerState: Equatable {
    static let supportedButtonMask: UInt32 = (1 << 13) - 1
    static let neutral = GameControllerState(
        buttonMask: 0,
        leftX: 0,
        leftY: 0,
        rightX: 0,
        rightY: 0,
        leftTrigger: 0,
        rightTrigger: 0,
        hatX: 0,
        hatY: 0
    )

    let buttonMask: UInt32
    let leftX: Double
    let leftY: Double
    let rightX: Double
    let rightY: Double
    let leftTrigger: Double
    let rightTrigger: Double
    let hatX: Int32
    let hatY: Int32

    var isValid: Bool {
        buttonMask & ~Self.supportedButtonMask == 0
            && [leftX, leftY, rightX, rightY].allSatisfy { $0.isFinite && (-1...1).contains($0) }
            && [leftTrigger, rightTrigger].allSatisfy { $0.isFinite && (0...1).contains($0) }
            && (-1...1).contains(hatX)
            && (-1...1).contains(hatY)
    }
}

enum GameControllerHIDReport {
    static let byteCount = 16

    /// Standard game-pad collection: 13 buttons, two sticks, two triggers and
    /// one null-capable hat. Seven trailing bytes are constant padding so the
    /// wire-to-kernel report has a stable 16-byte ABI.
    static let descriptor = Data([
        0x05, 0x01,       // Usage Page (Generic Desktop)
        0x09, 0x05,       // Usage (Game Pad)
        0xA1, 0x01,       // Collection (Application)
        0x05, 0x09,       //   Usage Page (Button)
        0x19, 0x01,       //   Usage Minimum (Button 1)
        0x29, 0x0D,       //   Usage Maximum (Button 13)
        0x15, 0x00,       //   Logical Minimum (0)
        0x25, 0x01,       //   Logical Maximum (1)
        0x75, 0x01,       //   Report Size (1)
        0x95, 0x0D,       //   Report Count (13)
        0x81, 0x02,       //   Input (Data, Variable, Absolute)
        0x75, 0x03,       //   Report Size (3)
        0x95, 0x01,       //   Report Count (1)
        0x81, 0x03,       //   Input (Constant)
        0x05, 0x01,       //   Usage Page (Generic Desktop)
        0x09, 0x30,       //   Usage (X)
        0x09, 0x31,       //   Usage (Y)
        0x09, 0x33,       //   Usage (Rx)
        0x09, 0x34,       //   Usage (Ry)
        0x15, 0x81,       //   Logical Minimum (-127)
        0x25, 0x7F,       //   Logical Maximum (127)
        0x75, 0x08,       //   Report Size (8)
        0x95, 0x04,       //   Report Count (4)
        0x81, 0x02,       //   Input (Data, Variable, Absolute)
        0x09, 0x32,       //   Usage (Z / left trigger)
        0x09, 0x35,       //   Usage (Rz / right trigger)
        0x15, 0x00,       //   Logical Minimum (0)
        0x26, 0xFF, 0x00, //   Logical Maximum (255)
        0x75, 0x08,       //   Report Size (8)
        0x95, 0x02,       //   Report Count (2)
        0x81, 0x02,       //   Input (Data, Variable, Absolute)
        0x09, 0x39,       //   Usage (Hat Switch)
        0x15, 0x00,       //   Logical Minimum (0)
        0x25, 0x07,       //   Logical Maximum (7)
        0x35, 0x00,       //   Physical Minimum (0)
        0x46, 0x3B, 0x01, //   Physical Maximum (315)
        0x65, 0x14,       //   Unit (Degrees)
        0x75, 0x04,       //   Report Size (4)
        0x95, 0x01,       //   Report Count (1)
        0x81, 0x42,       //   Input (Data, Variable, Absolute, Null State)
        0x65, 0x00,       //   Unit (None)
        0x75, 0x04,       //   Report Size (4)
        0x95, 0x01,       //   Report Count (1)
        0x81, 0x03,       //   Input (Constant)
        0x75, 0x08,       //   Report Size (8)
        0x95, 0x07,       //   Report Count (7)
        0x81, 0x03,       //   Input (Constant)
        0xC0,             // End Collection
    ])

    static func encode(_ state: GameControllerState) throws -> Data {
        guard state.isValid else { throw GameControllerInputError.invalidState }
        var bytes = [UInt8](repeating: 0, count: byteCount)
        bytes[0] = UInt8(truncatingIfNeeded: state.buttonMask)
        bytes[1] = UInt8(truncatingIfNeeded: state.buttonMask >> 8)
        bytes[2] = UInt8(bitPattern: signedAxis(state.leftX))
        bytes[3] = UInt8(bitPattern: signedAxis(state.leftY))
        bytes[4] = UInt8(bitPattern: signedAxis(state.rightX))
        bytes[5] = UInt8(bitPattern: signedAxis(state.rightY))
        bytes[6] = unsignedAxis(state.leftTrigger)
        bytes[7] = unsignedAxis(state.rightTrigger)
        bytes[8] = hatValue(x: state.hatX, y: state.hatY)
        return Data(bytes)
    }

    private static func signedAxis(_ value: Double) -> Int8 {
        Int8((value * 127).rounded().clamped(to: -127...127))
    }

    private static func unsignedAxis(_ value: Double) -> UInt8 {
        UInt8((value * 255).rounded().clamped(to: 0...255))
    }

    private static func hatValue(x: Int32, y: Int32) -> UInt8 {
        switch (x, y) {
        case (0, -1): return 0
        case (1, -1): return 1
        case (1, 0): return 2
        case (1, 1): return 3
        case (0, 1): return 4
        case (-1, 1): return 5
        case (-1, 0): return 6
        case (-1, -1): return 7
        default: return 8
        }
    }
}

private extension Double {
    func clamped(to range: ClosedRange<Double>) -> Double {
        min(max(self, range.lowerBound), range.upperBound)
    }
}

enum GameControllerInputError: Error, Equatable, LocalizedError {
    case unavailable(String)
    case invalidIdentity
    case invalidEpoch
    case invalidState
    case invalidTransition
    case maximumControllersReached
    case deviceCreationFailed
    case reportFailed(Int32)

    var errorDescription: String? {
        switch self {
        case .unavailable(let reason): return "Virtual game controller unavailable: \(reason)"
        case .invalidIdentity: return "Controller input or device identity is missing, oversized, or stale."
        case .invalidEpoch: return "Controller attachment epoch is invalid."
        case .invalidState: return "Controller state is outside the Protocol v1 range."
        case .invalidTransition: return "Controller event violates the attachment state machine."
        case .maximumControllersReached: return "At most four controllers can be attached."
        case .deviceCreationFailed: return "IOHIDUserDevice creation failed."
        case .reportFailed(let result): return "IOHIDUserDevice report failed with IOReturn \(result)."
        }
    }
}

protocol VirtualGamepadDevice: AnyObject {
    func submit(_ state: GameControllerState) throws
    func close() throws
}

protocol VirtualGamepadFactory {
    func makeDevice(controllerID: String, controllerEpoch: UInt64) throws -> VirtualGamepadDevice
}

enum GameControllerEventKind: Equatable {
    case connected
    case state
    case disconnected
}

struct GameControllerInputEvent: Equatable {
    let inputID: UInt64
    let controllerID: String
    let controllerEpoch: UInt64
    let kind: GameControllerEventKind
    let state: GameControllerState

    init?(wireEvent: VSControllerEvent) {
        let kind: GameControllerEventKind
        switch wireEvent.kind {
        case .connected: kind = .connected
        case .state: kind = .state
        case .disconnected: kind = .disconnected
        default: return nil
        }
        let state = GameControllerState(
            buttonMask: wireEvent.buttonMask,
            leftX: wireEvent.leftStickX,
            leftY: wireEvent.leftStickY,
            rightX: wireEvent.rightStickX,
            rightY: wireEvent.rightStickY,
            leftTrigger: wireEvent.leftTrigger,
            rightTrigger: wireEvent.rightTrigger,
            hatX: wireEvent.hatX,
            hatY: wireEvent.hatY
        )
        guard state.isValid else { return nil }
        self.init(
            inputID: wireEvent.inputID,
            controllerID: wireEvent.controllerID,
            controllerEpoch: wireEvent.controllerEpoch,
            kind: kind,
            state: state
        )
    }

    init(
        inputID: UInt64,
        controllerID: String,
        controllerEpoch: UInt64,
        kind: GameControllerEventKind,
        state: GameControllerState
    ) {
        self.inputID = inputID
        self.controllerID = controllerID
        self.controllerEpoch = controllerEpoch
        self.kind = kind
        self.state = state
    }
}

typealias GameControllerEventHandler =
    @MainActor (GameControllerInputEvent, UInt64) -> Bool

enum GameControllerEventDelivery {
    @MainActor
    static func deliver(
        _ event: GameControllerInputEvent,
        generation: UInt64,
        using handler: GameControllerEventHandler?
    ) -> Bool {
        handler?(event, generation) == true
    }
}

final class SessionGameControllerInput: @unchecked Sendable {
    private let lock = NSLock()
    private let injector: GameControllerInjector

    init(injector: GameControllerInjector) {
        self.injector = injector
    }

    func handle(_ event: GameControllerInputEvent, generation: UInt64) throws {
        lock.lock()
        defer { lock.unlock() }
        try injector.handle(event, generation: generation)
    }

    func reset() throws {
        lock.lock()
        defer { lock.unlock() }
        try injector.reset()
    }
}

final class SessionGameControllerInputRoute: @unchecked Sendable {
    private let lock = NSLock()
    private let input: SessionGameControllerInput
    private var active = true
    private var resetError: Error?

    init(input: SessionGameControllerInput) {
        self.input = input
    }

    func handle(_ event: GameControllerInputEvent, generation: UInt64) throws {
        lock.lock()
        defer { lock.unlock() }
        guard active else { throw resetError ?? GameControllerInputError.invalidTransition }
        try input.handle(event, generation: generation)
    }

    func invalidate() {
        lock.lock()
        guard active else {
            lock.unlock()
            return
        }
        active = false
        do {
            try input.reset()
        } catch {
            resetError = error
        }
        lock.unlock()
    }
}

enum GameControllerAdmissionResult: Equatable {
    case accepted
    case rejectedMaximumActiveControllers
}

enum GameControllerContract {
    static let maximumActiveControllers = 4
    static let maximumActiveControllersRejectionReason =
        "maximum_active_controllers_exceeded"
}

struct GameControllerStateMachine {
    static let maximumControllerIDBytes = 128
    private(set) var attachments: [String: UInt64] = [:]
    static let defaultMaximumControllers = GameControllerContract.maximumActiveControllers
    private var lastEpochs: [String: UInt64] = [:]
    private var lastInputID: UInt64 = 0
    let maximumControllers: Int

    init(maximumControllers: Int = GameControllerStateMachine.defaultMaximumControllers) {
        self.maximumControllers = maximumControllers
    }

    mutating func accept(_ event: GameControllerInputEvent) throws -> GameControllerAdmissionResult {
        guard event.inputID > lastInputID else { throw GameControllerInputError.invalidIdentity }
        guard !event.controllerID.isEmpty,
              event.controllerID.utf8.count <= Self.maximumControllerIDBytes else {
            throw GameControllerInputError.invalidIdentity
        }
        guard event.controllerEpoch > 0 else { throw GameControllerInputError.invalidEpoch }
        guard event.state.isValid else { throw GameControllerInputError.invalidState }

        switch event.kind {
        case .connected:
            guard event.state == .neutral,
                  attachments[event.controllerID] == nil,
                  event.controllerEpoch > (lastEpochs[event.controllerID] ?? 0) else {
                throw GameControllerInputError.invalidTransition
            }
            guard attachments.count < maximumControllers else {
                // Soft reject: the session layer must be able to acknowledge
                // this event's input_id, so consume it into the monotonic
                // counter. All admitted controllers are left untouched.
                lastInputID = event.inputID
                return .rejectedMaximumActiveControllers
            }
            attachments[event.controllerID] = event.controllerEpoch
            lastEpochs[event.controllerID] = event.controllerEpoch
        case .state:
            guard attachments[event.controllerID] == event.controllerEpoch else {
                throw GameControllerInputError.invalidTransition
            }
        case .disconnected:
            guard event.state == .neutral,
                  attachments[event.controllerID] == event.controllerEpoch else {
                throw GameControllerInputError.invalidTransition
            }
            attachments.removeValue(forKey: event.controllerID)
        }
        lastInputID = event.inputID
        return .accepted
    }

    mutating func reset() {
        attachments.removeAll()
        lastEpochs.removeAll()
        lastInputID = 0
    }
}

final class GameControllerInjector {
    private struct Attachment {
        let epoch: UInt64
        let device: VirtualGamepadDevice
    }

    private let factory: VirtualGamepadFactory
    private let maximumControllers: Int
    private var generation: UInt64?
    private var attachments: [String: Attachment] = [:]

    init(factory: VirtualGamepadFactory, maximumControllers: Int = GameControllerStateMachine.defaultMaximumControllers) {
        self.factory = factory
        self.maximumControllers = maximumControllers
    }

    func handle(_ event: GameControllerInputEvent, generation: UInt64) throws {
        if self.generation != generation {
            try reset()
            self.generation = generation
        }
        switch event.kind {
        case .connected:
            guard event.state == .neutral,
                  attachments[event.controllerID] == nil else {
                throw GameControllerInputError.invalidTransition
            }
            guard attachments.count < maximumControllers else {
                throw GameControllerInputError.maximumControllersReached
            }
            let device = try factory.makeDevice(
                controllerID: event.controllerID,
                controllerEpoch: event.controllerEpoch
            )
            do {
                try device.submit(.neutral)
                attachments[event.controllerID] = Attachment(
                    epoch: event.controllerEpoch,
                    device: device
                )
            } catch {
                try? device.close()
                throw error
            }
        case .state:
            guard let attachment = attachments[event.controllerID],
                  attachment.epoch == event.controllerEpoch else {
                throw GameControllerInputError.invalidTransition
            }
            try attachment.device.submit(event.state)
        case .disconnected:
            guard event.state == .neutral,
                  let attachment = attachments[event.controllerID],
                  attachment.epoch == event.controllerEpoch else {
                throw GameControllerInputError.invalidTransition
            }
            attachments.removeValue(forKey: event.controllerID)
            var firstError: Error?
            do {
                try attachment.device.submit(.neutral)
            } catch {
                firstError = error
            }
            do {
                try attachment.device.close()
            } catch {
                if firstError == nil { firstError = error }
            }
            if let firstError { throw firstError }
        }
    }

    func reset() throws {
        let devices = attachments.keys.sorted().compactMap { attachments[$0]?.device }
        attachments.removeAll()
        generation = nil
        var firstError: Error?
        for device in devices {
            // Neutralize every active controller before tearing it down so the
            // host never observes a stuck button or axis after a reset.
            do {
                try device.submit(.neutral)
            } catch {
                if firstError == nil { firstError = error }
            }
            do {
                try device.close()
            } catch {
                if firstError == nil { firstError = error }
            }
        }
        if let firstError { throw firstError }
    }
}
