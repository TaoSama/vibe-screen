import Foundation

enum HostCommandLine {
    enum Command: Equatable {
        case issuePhase3InternetLease
        case transportSelfTest
        case reliabilitySelfTest
        case protocolV1SelfTest
        case videoEncoderSelfTest
        case audioCaptureSelfTest
        case hostSelfTest
        case phase3InternetSelfTest
        case phase3InternetLeaseSelfTest
        case phase3WebRTCLoopbackSelfTest
        case phase3WebRTCSignalingSelfTest
        case phase3ProductSignalingSelfTest
        case phase3ProductAndroidInteropHost
        case phase3RealMediaSelfTest
        case iOSLoopback(expectsInvalidTarget: Bool)
    }

    enum LaunchMode: Equatable {
        case command(Command)
        case gui
        case rejected
    }

    struct ParseResult: Equatable {
        let launchMode: LaunchMode
        let errorMessage: String?

        var canLaunch: Bool { errorMessage == nil }
    }

    private static let commandFlags: [String: Command] = [
        "--issue-phase3-internet-lease": .issuePhase3InternetLease,
        "--transport-self-test": .transportSelfTest,
        "--reliability-self-test": .reliabilitySelfTest,
        "--protocol-v1-self-test": .protocolV1SelfTest,
        "--video-encoder-self-test": .videoEncoderSelfTest,
        "--audio-capture-self-test": .audioCaptureSelfTest,
        "--host-self-test": .hostSelfTest,
        "--phase3-internet-self-test": .phase3InternetSelfTest,
        "--phase3-internet-lease-self-test": .phase3InternetLeaseSelfTest,
        "--phase3-webrtc-loopback-self-test": .phase3WebRTCLoopbackSelfTest,
        "--phase3-webrtc-signaling-self-test": .phase3WebRTCSignalingSelfTest,
        "--phase3-product-signaling-self-test": .phase3ProductSignalingSelfTest,
        "--phase3-product-android-interop-host": .phase3ProductAndroidInteropHost,
        "--phase3-real-media-self-test": .phase3RealMediaSelfTest
    ]

    private static let guiFlags: Set<String> = [
        "--headless-benchmark",
        "--prefer-cgdisplaystream"
    ]

    static var supportedDoubleDashFlags: Set<String> {
        Set(commandFlags.keys).union(guiFlags)
    }

    static func parse(arguments: [String]) -> ParseResult {
        parse(arguments: arguments, environment: ProcessInfo.processInfo.environment)
    }

    static func parse(arguments: [String], environment: [String: String]) -> ParseResult {
        let flags = arguments.dropFirst()
        if let unknownFlag = flags.first(where: { isUnknownDoubleDashFlag($0) }) {
            return ParseResult(
                launchMode: .rejected,
                errorMessage: "Unknown Vibe Screen Host CLI flag: \(unknownFlag)"
            )
        }

        let commands = flags.compactMap { commandFlags[String($0)] }
        if commands.count > 1 {
            return ParseResult(
                launchMode: .rejected,
                errorMessage: "Multiple Vibe Screen Host CLI commands are not supported."
            )
        }

        let loopbackCommand: Command?
        if let scenario = environment["VIBE_SCREEN_IOS_LOOPBACK_SCENARIO"] {
            switch scenario {
            case "lifecycle":
                loopbackCommand = .iOSLoopback(expectsInvalidTarget: false)
            case "invalid-target":
                loopbackCommand = .iOSLoopback(expectsInvalidTarget: true)
            default:
                return ParseResult(launchMode: .rejected, errorMessage: "Unknown iOS loopback scenario.")
            }
        } else {
            loopbackCommand = nil
        }

        if !commands.isEmpty, loopbackCommand != nil {
            return ParseResult(
                launchMode: .rejected,
                errorMessage: "Vibe Screen Host CLI commands cannot be combined with iOS loopback mode."
            )
        }

        if let command = commands.first {
            return ParseResult(launchMode: .command(command), errorMessage: nil)
        }
        if let loopbackCommand {
            return ParseResult(launchMode: .command(loopbackCommand), errorMessage: nil)
        }

        return ParseResult(launchMode: .gui, errorMessage: nil)
    }

    private static func isUnknownDoubleDashFlag(_ argument: String) -> Bool {
        argument.hasPrefix("--") && !supportedDoubleDashFlags.contains(argument)
    }
}
