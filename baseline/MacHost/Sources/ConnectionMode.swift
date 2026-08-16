import Foundation

enum ConnectionMode: String, Codable, CaseIterable {
    case usb
    case wireless
    case internet

    var title: String {
        switch self {
        case .usb: return "USB"
        case .wireless: return "Wireless"
        case .internet: return "Internet"
        }
    }

    var systemImage: String {
        switch self {
        case .usb: return "cable.connector"
        case .wireless: return "wifi"
        case .internet: return "globe"
        }
    }
}

enum InternetRoutePreference: String, Codable, CaseIterable, Identifiable {
    case preferDirect
    case forceTURN

    var id: String { rawValue }

    var title: String {
        switch self {
        case .preferDirect: return "Prefer direct"
        case .forceTURN: return "Force TURN"
        }
    }

    var helpText: String {
        switch self {
        case .preferDirect:
            return "Uses a direct peer path when available and falls back to TURN."
        case .forceTURN:
            return "Routes through TURN for diagnostics. Protocol v1 application-record encryption is enabled in this development preview; Internet security acceptance is incomplete."
        }
    }
}

enum InternetConnectionStatus: Equatable {
    case idle
    case pairing
    case paired
    case connecting
    case direct
    case relay
    case recovering
    case revoked
    case failed

    var title: String {
        switch self {
        case .idle: return "Not paired"
        case .pairing: return "Pairing"
        case .paired: return "Paired"
        case .connecting: return "Connecting"
        case .direct: return "Direct"
        case .relay: return "Relay"
        case .recovering: return "Recovering"
        case .revoked: return "Revoked"
        case .failed: return "Failed"
        }
    }

    var isActive: Bool {
        switch self {
        case .connecting, .direct, .relay: return true
        default: return false
        }
    }

    var canConnect: Bool {
        switch self {
        case .paired, .recovering, .failed: return true
        default: return false
        }
    }
}

struct InternetAdaptiveMediaControlState: Equatable {
    var isActive = false
    var bitrateMbps = 0
    var framesPerSecond = 0
    var quality = ""

    static let inactive = Self()

    var allowsManualChanges: Bool { !isActive }

    /// Single-line real-time summary shown while an Internet adaptive session
    /// owns the live encoder settings.
    var summary: String {
        "Internet adaptive · \(bitrateMbps) Mbps · \(framesPerSecond) FPS"
    }

    static func active(
        bitrateMbps: Int,
        framesPerSecond: Int,
        quality: String
    ) -> Self {
        Self(
            isActive: true,
            bitrateMbps: bitrateMbps,
            framesPerSecond: framesPerSecond,
            quality: quality
        )
    }
}
