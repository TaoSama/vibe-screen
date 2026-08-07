import Foundation
import Security

extension InternetProductSession {
    static func makeStoredSecuritySession(
        configuration: InternetProductSessionConfiguration
    ) throws -> InternetProductSecuritySession {
        let stateStore = KeychainSecurityStateStore(peerID: configuration.peerSecurityScopeID)
        let platformSecurity = PlatformSessionSecurity(
            deviceID: configuration.hostDeviceID,
            peerID: configuration.peerSecurityScopeID,
            stateStore: stateStore
        )
        let active = try platformSecurity.startStoredProtectedInternetSession(
            sessionIdentifier: configuration.transport.sessionIdentifier,
            localRole: PlatformSenderRole.host,
            identityEpoch: configuration.identityEpoch,
            secretNames: try PairedDeviceSecretNames.persistedPairing(
                sharedSecret: configuration.sharedSecretName,
                bootstrapSecret: configuration.bootstrapSecretName
            ),
            transcriptContext: configuration.boundTranscriptContext,
            agreedSessionEpoch: configuration.authoritativeSessionEpoch
        )
        return InternetProductSecuritySession(
            sessionEpoch: active.sessionEpoch,
            packetCipher: active.packetCipher
        )
    }

    static func persistPeerRevocation(
        configuration: InternetProductSessionConfiguration,
        sequence: UInt64
    ) throws -> PairedDeviceRevocationTombstone? {
        let secretNames = try PairedDeviceSecretNames.persistedPairing(
            sharedSecret: configuration.sharedSecretName,
            bootstrapSecret: configuration.bootstrapSecretName
        )
        guard let pairingIdentifier = secretNames.pairingIdentifier else {
            throw PlatformSecurityError.persistenceFailure(
                "The paired-device durable security owner is unknown. Pair again."
            )
        }
        let stateStore = KeychainSecurityStateStore(
            peerID: configuration.peerSecurityScopeID
        )
        _ = try stateStore.validatePairingBinding(
            pairingIdentifier: pairingIdentifier
        )
        guard let identityBindingName = secretNames.identityBinding,
              let encodedIdentityBinding = try KeychainSecretStore().load(
                name: identityBindingName
              ) else {
            throw PlatformSecurityError.persistenceFailure(
                "The paired host identity binding is missing. Pair again; existing credentials were retained."
            )
        }
        let identityBinding = try PairedHostIdentityBinding.decode(encodedIdentityBinding)
        guard identityBinding.deviceID == configuration.hostDeviceID,
              identityBinding.keyEpoch == configuration.identityEpoch else {
            throw PlatformSecurityError.persistenceFailure(
                "The paired host identity binding targets another device or key epoch. Pair again."
            )
        }
        let identityStore = KeychainDeviceIdentityStore()
        let authority = try identityStore.loadVerifiedExisting(binding: identityBinding)
        var nonce = Data(count: 32)
        let randomStatus = nonce.withUnsafeMutableBytes { bytes in
            SecRandomCopyBytes(kSecRandomDefault, bytes.count, bytes.baseAddress!)
        }
        guard randomStatus == errSecSuccess else {
            throw PlatformSecurityError.persistenceFailure(
                "Unable to generate the paired-device revocation nonce."
            )
        }
        let tombstone = try authority.signPeerRevocation(
            peerIdentity: configuration.peerIdentity,
            sequence: sequence,
            revokedAtUnixSeconds: Int64(Date().timeIntervalSince1970),
            nonce: nonce,
            reasonCode: "user_revoked"
        )
        let platformSecurity = PlatformSessionSecurity(
            deviceID: configuration.hostDeviceID,
            peerID: configuration.peerSecurityScopeID,
            identityStore: identityStore,
            stateStore: stateStore
        )
        try platformSecurity.requirePairingBinding(pairingIdentifier)
        try platformSecurity.revokePeer(
            tombstone,
            expectedAuthority: authority.publicIdentity,
            expectedPeer: configuration.peerIdentity,
            secretNames: secretNames
        )
        return tombstone
    }
}
