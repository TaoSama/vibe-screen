import Foundation
import UIKit
import VibeScreenCore
import VibeScreenProtocol

extension StreamViewModel {
    func connect(pairing: TrustedLANPairing, generation: UInt64) async {
        guard !Task.isCancelled,
              closingSessionOwner == nil,
              reconnectCoordinator.accepts(generation: generation),
              activePairing == pairing else { return }
        let policy = managedConfiguration.policy
        let connectionOwner = ConnectionOwner()
        let owner = SessionOwner(connectionOwner: connectionOwner)
        deliveryGate.reset(to: connectionOwner)
        sessionOwner = owner
        sessionLocalManagedPolicy = policy
        sessionManagedPolicy = policy
        connectionGeneration = generation
        controlOutbox.activate(owner: owner)
        setConnecting(true)
        defer {
            if sessionOwner == owner { setConnecting(false) }
        }
        errorMessage = nil
        do {
            try state.beginConnection()
            try await transport.connect(
                pairing: pairing,
                deviceName: UIDevice.current.name,
                owner: connectionOwner
            )
            guard acceptsConnection(owner: owner, pairing: pairing, generation: generation) else { return }
            try state.transportConnected()
            controlValidator.reset()
            try await controlOutbox.sendAndWait(owner: owner) { factory in
                factory.clientHello(
                    deviceID: self.deviceID,
                    deviceName: UIDevice.current.name,
                    capabilities: self.advertisedCapabilities(policy: policy),
                    codecs: [.hevc, .h264],
                    resourceLimits: self.clientResourceLimits(policy: policy),
                    videoDecodeCapabilities: Self.sdrDecodeCapabilities
                )
            }
            guard acceptsConnection(owner: owner, pairing: pairing, generation: generation) else { return }
        } catch {
            guard sessionOwner == owner,
                  reconnectCoordinator.accepts(generation: generation) else { return }
            terminateSession(
                message: error.localizedDescription,
                failure: ReconnectFailure.classify(error),
                generation: generation
            )
        }
    }

    func terminateSession(
        message: String,
        failure: ReconnectFailure,
        generation: UInt64? = nil
    ) {
        guard closingSessionOwner == nil else { return }
        let currentGeneration = generation ?? connectionGeneration
        let schedule = currentGeneration.flatMap { candidate in
            reconnectCoordinator.schedule(generation: candidate, failure: failure)
        }

        reconnectTask?.cancel()
        reconnectTask = nil
        state.fail(message)
        errorMessage = message
        endSession(disconnectTransport: true, resetState: false)

        guard let schedule, let pairing = activePairing else {
            stopAutomaticReconnect(clearPairing: true)
            return
        }

        state.disconnected(retryAttempt: schedule.attempt)
        errorMessage = "\(message)；\(String(format: "%.2g", schedule.delaySeconds)) 秒后重试"
        reconnectTask = Task { [weak self] in
            do {
                try await Task.sleep(for: .milliseconds(Int(schedule.delaySeconds * 1_000)))
                try Task.checkCancellation()
            } catch {
                return
            }
            guard let self,
                  !Task.isCancelled,
                  self.reconnectCoordinator.accepts(generation: schedule.generation),
                  self.activePairing == pairing else { return }
            self.reconnectTask = nil
            await self.connect(pairing: pairing, generation: schedule.generation)
        }
    }

    func stopAutomaticReconnect(clearPairing: Bool) {
        reconnectCoordinator.stop()
        reconnectTask?.cancel()
        reconnectTask = nil
        if clearPairing { activePairing = nil }
    }

    private func acceptsConnection(
        owner: SessionOwner,
        pairing: TrustedLANPairing,
        generation: UInt64
    ) -> Bool {
        !Task.isCancelled
            && closingSessionOwner == nil
            && reconnectCoordinator.accepts(generation: generation)
            && activePairing == pairing
            && sessionOwner == owner
    }
}
