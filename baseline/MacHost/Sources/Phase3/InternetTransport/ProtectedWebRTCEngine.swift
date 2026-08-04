import Foundation

/// Applies the Protocol v1 AES-GCM record layer at the production WebRTC
/// boundary. The wrapped SDK only handles authenticated ciphertext.
final class ProtectedWebRTCEngine: WebRTCEnginePort {
    private let engine: WebRTCEnginePort
    private let packetCipher: PlatformSessionPacketCipher
    private let limits: InternetTransportLimits
    private let lock = NSLock()
    private var callbacks: WebRTCEngineCallbacks?
    private var closed = false
    private var authenticationFailureCount = 0
    private static let maximumAuthenticationFailures = 3

    init(
        engine: WebRTCEnginePort,
        packetCipher: PlatformSessionPacketCipher,
        limits: InternetTransportLimits = .standard
    ) {
        self.engine = engine
        self.packetCipher = packetCipher
        self.limits = limits
    }

    func install(callbacks: WebRTCEngineCallbacks) {
        lock.withProtectedEngineLock { self.callbacks = callbacks }
        engine.install(callbacks: WebRTCEngineCallbacks(
            connectionStateChanged: callbacks.connectionStateChanged,
            networkPathChanged: callbacks.networkPathChanged,
            networkQualitySampled: callbacks.networkQualitySampled,
            messageReceived: { [weak self] record, channel in
                guard let self else { return }
                let plaintextMaximum = channel == .control
                    ? self.limits.maximumControlMessageBytes
                    : self.limits.maximumMediaFrameBytes
                let encryptedMaximum = plaintextMaximum + PlatformSessionPacketCipher.recordOverhead
                guard record.count <= encryptedMaximum else {
                    callbacks.connectionStateChanged(.failed(
                        "Encrypted \(channel) record exceeded the configured inbound limit."
                    ))
                    return
                }
                guard let plaintext = self.packetCipher.open(record, channel: channel) else {
                    let exhausted = self.lock.withProtectedEngineLock { () -> Bool in
                        guard !self.closed else { return false }
                        self.authenticationFailureCount += 1
                        return self.authenticationFailureCount >= Self.maximumAuthenticationFailures
                    }
                    if exhausted {
                        callbacks.connectionStateChanged(.failed(
                            "Application E2EE authentication failure budget was exhausted."
                        ))
                    }
                    return
                }
                let callback = self.lock.withProtectedEngineLock { () -> ((Data, InternetTransportChannel) -> Void)? in
                    guard !self.closed else { return nil }
                    self.authenticationFailureCount = 0
                    return self.callbacks?.messageReceived
                }
                guard let callback else { return }
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
            authenticationFailureCount = 0
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
