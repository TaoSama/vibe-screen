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
            sharedSecretName: configuration.sharedSecretName,
            bootstrapSecretName: configuration.bootstrapSecretName,
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
        let identityStore = KeychainDeviceIdentityStore()
        let authority = try identityStore.loadOrCreate(
            deviceID: configuration.hostDeviceID,
            keyEpoch: configuration.identityEpoch
        )
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
        let stateStore = KeychainSecurityStateStore(peerID: configuration.peerSecurityScopeID)
        let platformSecurity = PlatformSessionSecurity(
            deviceID: configuration.hostDeviceID,
            peerID: configuration.peerSecurityScopeID,
            identityStore: identityStore,
            stateStore: stateStore
        )
        let secretNames = try PairedDeviceSecretNames(
            sharedSecret: configuration.sharedSecretName,
            bootstrapSecret: configuration.bootstrapSecretName
        )
        try platformSecurity.revokePeer(
            tombstone,
            expectedAuthority: authority.publicIdentity,
            expectedPeer: configuration.peerIdentity,
            secretNames: secretNames
        )
        return tombstone
    }
}
