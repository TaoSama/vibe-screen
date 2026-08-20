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
            transmissionContextChanged: callbacks.transmissionContextChanged,
            networkPathChanged: callbacks.networkPathChanged,
            networkQualitySampled: callbacks.networkQualitySampled,
            messageReceived: { [weak self] record, channel in
                guard let self else { return }
                let encryptedMaximum = self.maximumEncryptedRecordBytes(for: channel)
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
                            "Protocol v1 application-record authentication failed repeatedly; the development-preview session was closed."
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
        expectedContext: WebRTCEngineTransmissionContext,
        completion: @escaping (Result<Void, Error>) -> Void
    ) {
        do {
            let maximumPlaintextBytes = maximumPlaintextRecordBytes(for: channel)
            if payload.count > maximumPlaintextBytes {
                throw InternetTransportError.payloadTooLarge(
                    channel: channel,
                    actual: payload.count,
                    maximum: maximumPlaintextBytes
                )
            }
            let record = try packetCipher.seal(payload, channel: channel)
            let maximumEncryptedBytes = maximumEncryptedRecordBytes(for: channel)
            if record.count > maximumEncryptedBytes {
                throw InternetTransportError.payloadTooLarge(
                    channel: channel,
                    actual: record.count,
                    maximum: maximumEncryptedBytes
                )
            }
            engine.send(
                record,
                channel: channel,
                expectedContext: expectedContext,
                completion: completion
            )
        } catch {
            completion(.failure(error))
        }
    }

    func restartICE() -> WebRTCEngineRecoveryDisposition { engine.restartICE() }
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

    private func maximumEncryptedRecordBytes(for channel: InternetTransportChannel) -> Int {
        switch channel {
        case .control:
            return limits.maximumControlMessageBytes + PlatformSessionPacketCipher.recordOverhead
        case .media:
            return InternetMediaRecordContract.maximumEncryptedRecordBytes
        case .audio:
            return InternetAudioRecordContract.maximumEncryptedRecordBytes
        case .bulk:
            return InternetBulkRecordContract.maximumEncryptedRecordBytes
        }
    }

    private func maximumPlaintextRecordBytes(for channel: InternetTransportChannel) -> Int {
        switch channel {
        case .control:
            return limits.maximumControlMessageBytes
        case .media:
            return InternetMediaRecordContract.maximumPlaintextRecordBytes
        case .audio:
            return InternetAudioRecordContract.maximumPlaintextRecordBytes
        case .bulk:
            return InternetBulkRecordContract.maximumPlaintextRecordBytes
        }
    }
}

private extension NSLock {
    func withProtectedEngineLock<T>(_ operation: () -> T) -> T {
        lock()
        defer { unlock() }
        return operation()
    }
}
