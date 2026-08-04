import Foundation

/// Applies the Protocol v1 AES-GCM record layer at the production WebRTC
/// boundary. The wrapped SDK only handles authenticated ciphertext.
final class ProtectedWebRTCEngine: WebRTCEnginePort {
    private let engine: WebRTCEnginePort
    private let packetCipher: PlatformSessionPacketCipher
    private let lock = NSLock()
    private var callbacks: WebRTCEngineCallbacks?
    private var closed = false

    init(engine: WebRTCEnginePort, packetCipher: PlatformSessionPacketCipher) {
        self.engine = engine
        self.packetCipher = packetCipher
    }

    func install(callbacks: WebRTCEngineCallbacks) {
        lock.withProtectedEngineLock { self.callbacks = callbacks }
        engine.install(callbacks: WebRTCEngineCallbacks(
            connectionStateChanged: callbacks.connectionStateChanged,
            networkPathChanged: callbacks.networkPathChanged,
            networkQualitySampled: callbacks.networkQualitySampled,
            messageReceived: { [weak self] record, channel in
                guard let self,
                      let plaintext = self.packetCipher.open(record, channel: channel),
                      let callback = self.lock.withProtectedEngineLock({ self.closed ? nil : self.callbacks?.messageReceived }) else {
                    return
                }
                callback(plaintext, channel)
            },
            selectedCandidatePairChanged: callbacks.selectedCandidatePairChanged
        ))
    }

    func start(
        configuration: WebRTCTransportConfiguration,
        channels: [WebRTCDataChannelConfiguration]
    ) throws {
        guard configuration.sessionIdentifier == packetCipher.sessionIdentifier else {
            throw InternetTransportError.invalidConfiguration(
                "The application cipher is bound to a different signaling session."
            )
        }
        try engine.start(configuration: configuration, channels: channels)
    }

    func send(
        _ payload: Data,
        channel: InternetTransportChannel,
        completion: @escaping (Result<Void, Error>) -> Void
    ) {
        do {
            let record = try packetCipher.seal(payload, channel: channel)
            engine.send(record, channel: channel, completion: completion)
        } catch {
            completion(.failure(error))
        }
    }

    func restartICE() { engine.restartICE() }
    func requestMediaKeyframe() { engine.requestMediaKeyframe() }

    func close() {
        let shouldClose = lock.withProtectedEngineLock { () -> Bool in
            guard !closed else { return false }
            closed = true
            callbacks = nil
            return true
        }
        guard shouldClose else { return }
        engine.close()
        packetCipher.close()
    }
}

private extension NSLock {
    func withProtectedEngineLock<T>(_ operation: () -> T) -> T {
        lock()
        defer { unlock() }
        return operation()
    }
}
