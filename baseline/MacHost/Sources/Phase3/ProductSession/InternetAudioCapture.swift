import Foundation
import VibeScreenProtocol

protocol InternetAudioCapture: AnyObject {
    var canAdvertiseCapture: Bool { get }

    func start(
        config: VSAudioConfig,
        sessionEpoch: UInt64,
        onPacket: @escaping @Sendable (Data) -> Void,
        onError: @escaping @Sendable (Error) -> Void
    ) throws

    func stop(reason: String)
}

final class MacHostInternetAudioCapture: InternetAudioCapture {
    private let stream: MacHostAudioStream

    init(stream: MacHostAudioStream = MacHostAudioStream()) {
        self.stream = stream
    }

    var canAdvertiseCapture: Bool { stream.canAdvertiseCapture }

    func start(
        config: VSAudioConfig,
        sessionEpoch: UInt64,
        onPacket: @escaping @Sendable (Data) -> Void,
        onError: @escaping @Sendable (Error) -> Void
    ) throws {
        try stream.start(
            config: config,
            sessionEpoch: sessionEpoch,
            onPacket: { packet in onPacket(packet.serializedFrame) },
            onError: onError
        )
    }

    func stop(reason _: String) {
        stream.stop()
    }
}
