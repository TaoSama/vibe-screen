import CryptoKit
import Foundation
import Security

enum InternetSessionLeaseIssuerError: Error, LocalizedError {
    case invalidInput(String)
    case pairedHostIdentityUnavailable

    var errorDescription: String? {
        switch self {
        case .invalidInput(let reason): return reason
        case .pairedHostIdentityUnavailable:
            return "The paired host identity binding or Keychain signing key is unavailable. Pair again before issuing a session lease."
        }
    }
}

struct InternetSessionLeaseICE: Equatable {
    let urls: [String]
    let username: String?
    let credential: String?
}

struct InternetSessionLeasePayload: Equatable {
    let pairingIdentifier: String
    let pinnedHostID: String
    let pinnedDeviceID: String
    let leaseDeviceKeyID: String
    let signalingURL: String
    let signalingSessionID: String
    let authoritativeSessionEpoch: UInt64
    let hostIdentityEpoch: UInt64
    let deviceIdentityEpoch: UInt64
    let expiresAtUnixSeconds: UInt64
    let transcriptContext: Data
    let protocolSessionID: Data
    let signalingToken: String
    let iceServers: [InternetSessionLeaseICE]
    let allowInsecureForTesting: Bool

    func authorizing(epoch: UInt64, expiresAtUnixSeconds: UInt64) -> Self {
        Self(
            pairingIdentifier: pairingIdentifier,
            pinnedHostID: pinnedHostID,
            pinnedDeviceID: pinnedDeviceID,
            leaseDeviceKeyID: leaseDeviceKeyID,
            signalingURL: signalingURL,
            signalingSessionID: signalingSessionID,
            authoritativeSessionEpoch: epoch,
            hostIdentityEpoch: hostIdentityEpoch,
            deviceIdentityEpoch: deviceIdentityEpoch,
            expiresAtUnixSeconds: expiresAtUnixSeconds,
            transcriptContext: transcriptContext,
            protocolSessionID: protocolSessionID,
            signalingToken: signalingToken,
            iceServers: iceServers,
            allowInsecureForTesting: allowInsecureForTesting
        )
    }
}

enum InternetSessionLeaseCodec {
    static let domain = "vibescreen/internet-session-lease/v1"
    private static let version: UInt64 = 1
    private static let rootKeys: Set<String> = [
        "version", "pairing_id", "pinned_host_id", "pinned_device_id",
        "lease_device_key_id", "signaling_url",
        "signaling_session_id", "session_epoch", "host_identity_epoch",
        "device_identity_epoch",
        "transcript_context", "protocol_session_id", "signaling_token",
        "ice_servers", "allow_insecure_for_testing"
    ]
    private static let iceKeys: Set<String> = ["urls", "username", "credential"]

    static func decodeUnsigned(_ data: Data) throws -> InternetSessionLeasePayload {
        guard !data.isEmpty, data.count <= 65_536 else {
            throw invalid("Internet lease is empty or too large.")
        }
        let value: Any
        do {
            value = try JSONSerialization.jsonObject(with: data, options: [])
        } catch {
            throw invalid("Internet lease is not valid JSON.")
        }
        guard let root = value as? [String: Any], Set(root.keys) == rootKeys else {
            throw invalid("Internet lease contains missing or unknown fields.")
        }
        guard try integer(root, "version") == version else {
            throw invalid("Unsupported Internet lease version.")
        }
        let signalingURL = try string(root, "signaling_url", maximumBytes: 2_048)
        let allowInsecure = try boolean(root, "allow_insecure_for_testing")
        try validateSignalingURL(signalingURL, allowInsecure: allowInsecure)
        let signalingToken = try string(root, "signaling_token", maximumBytes: 8_192)
        guard signalingToken.utf8.count >= 32 else {
            throw invalid("Signaling token is invalid.")
        }
        guard let rawICE = root["ice_servers"] as? [Any],
              (1...16).contains(rawICE.count) else {
            throw invalid("ICE server count is invalid.")
        }
        let iceServers = try rawICE.map { raw -> InternetSessionLeaseICE in
            guard let server = raw as? [String: Any], Set(server.keys) == iceKeys,
                  let rawURLs = server["urls"] as? [Any],
                  (1...8).contains(rawURLs.count) else {
                throw invalid("ICE server contains missing or unknown fields.")
            }
            let urls = try rawURLs.map { rawURL -> String in
                guard let url = rawURL as? String, !url.isEmpty,
                      url.utf8.count <= 2_048 else {
                    throw invalid("ICE URL is invalid.")
                }
                return url
            }
            let username = try nullableString(server, "username", maximumBytes: 4_096)
            let credential = try nullableString(server, "credential", maximumBytes: 4_096)
            try validateICE(urls: urls, username: username, credential: credential)
            return InternetSessionLeaseICE(
                urls: urls,
                username: username,
                credential: credential
            )
        }
        return InternetSessionLeasePayload(
            pairingIdentifier: try string(root, "pairing_id", maximumBytes: 256),
            pinnedHostID: try string(root, "pinned_host_id", maximumBytes: 256),
            pinnedDeviceID: try string(root, "pinned_device_id", maximumBytes: 256),
            leaseDeviceKeyID: try string(root, "lease_device_key_id", maximumBytes: 256),
            signalingURL: signalingURL,
            signalingSessionID: try string(root, "signaling_session_id", maximumBytes: 256),
            authoritativeSessionEpoch: try positiveEpoch(root, "session_epoch"),
            hostIdentityEpoch: try positiveEpoch(root, "host_identity_epoch"),
            deviceIdentityEpoch: try positiveEpoch(root, "device_identity_epoch"),
            expiresAtUnixSeconds: 0,
            transcriptContext: try base64(root, "transcript_context", sizes: 32...32),
            protocolSessionID: try base64(root, "protocol_session_id", sizes: 1...256),
            signalingToken: signalingToken,
            iceServers: iceServers,
            allowInsecureForTesting: allowInsecure
        )
    }

    static func digest(
        _ payload: InternetSessionLeasePayload,
        leaseHostKeyID: String
    ) -> Data {
        var parts: [Data] = [
            SecurityTranscript.uint64(version),
            Data(payload.pairingIdentifier.utf8),
            Data(payload.pinnedHostID.utf8),
            Data(leaseHostKeyID.utf8),
            Data(payload.pinnedDeviceID.utf8),
            Data(payload.leaseDeviceKeyID.utf8),
            Data(payload.signalingURL.utf8),
            Data(payload.signalingSessionID.utf8),
            SecurityTranscript.uint64(payload.authoritativeSessionEpoch),
            SecurityTranscript.uint64(payload.hostIdentityEpoch),
            SecurityTranscript.uint64(payload.deviceIdentityEpoch),
            SecurityTranscript.uint64(payload.expiresAtUnixSeconds),
            payload.transcriptContext,
            payload.protocolSessionID,
            Data(payload.signalingToken.utf8),
            SecurityTranscript.uint64(UInt64(payload.iceServers.count))
        ]
        for server in payload.iceServers {
            parts.append(SecurityTranscript.uint64(UInt64(server.urls.count)))
            parts.append(contentsOf: server.urls.map { Data($0.utf8) })
            appendNullable(server.username, to: &parts)
            appendNullable(server.credential, to: &parts)
        }
        parts.append(Data([payload.allowInsecureForTesting ? 1 : 0]))
        return SecurityTranscript.digest(domain: domain, parts: parts)
    }

    static func encodeSigned(
        _ payload: InternetSessionLeasePayload,
        leaseHostKeyID: String,
        signature: Data
    ) throws -> Data {
        let ice: [[String: Any]] = payload.iceServers.map {
            [
                "urls": $0.urls,
                "username": $0.username ?? NSNull(),
                "credential": $0.credential ?? NSNull()
            ]
        }
        let root: [String: Any] = [
            "version": 1,
            "pairing_id": payload.pairingIdentifier,
            "pinned_host_id": payload.pinnedHostID,
            "pinned_device_id": payload.pinnedDeviceID,
            "lease_device_key_id": payload.leaseDeviceKeyID,
            "signaling_url": payload.signalingURL,
            "signaling_session_id": payload.signalingSessionID,
            "session_epoch": payload.authoritativeSessionEpoch,
            "host_identity_epoch": payload.hostIdentityEpoch,
            "device_identity_epoch": payload.deviceIdentityEpoch,
            "expires_at": payload.expiresAtUnixSeconds,
            "transcript_context": payload.transcriptContext.base64EncodedString(),
            "protocol_session_id": payload.protocolSessionID.base64EncodedString(),
            "signaling_token": payload.signalingToken,
            "ice_servers": ice,
            "allow_insecure_for_testing": payload.allowInsecureForTesting,
            "lease_host_key_id": leaseHostKeyID,
            "lease_signature": signature.base64EncodedString()
        ]
        return try JSONSerialization.data(withJSONObject: root, options: [.sortedKeys])
    }

    static func verifyDigestSignature(
        _ signature: Data,
        digest: Data,
        publicKey: Data
    ) -> Bool {
        let attributes: [String: Any] = [
            kSecAttrKeyType as String: kSecAttrKeyTypeECSECPrimeRandom,
            kSecAttrKeyClass as String: kSecAttrKeyClassPublic,
            kSecAttrKeySizeInBits as String: 256
        ]
        guard digest.count == SHA256.byteCount,
              let key = SecKeyCreateWithData(
                publicKey as CFData,
                attributes as CFDictionary,
                nil
              ) else { return false }
        return SecKeyVerifySignature(
            key,
            .ecdsaSignatureDigestX962SHA256,
            digest as CFData,
            signature as CFData,
            nil
        )
    }

    private static func appendNullable(_ value: String?, to parts: inout [Data]) {
        parts.append(Data([value == nil ? 0 : 1]))
        if let value { parts.append(Data(value.utf8)) }
    }

    private static func string(
        _ root: [String: Any],
        _ name: String,
        maximumBytes: Int
    ) throws -> String {
        guard let value = root[name] as? String,
              !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              value.utf8.count <= maximumBytes else {
            throw invalid("\(name) must be a bounded non-empty string.")
        }
        return value
    }

    private static func nullableString(
        _ root: [String: Any],
        _ name: String,
        maximumBytes: Int
    ) throws -> String? {
        if root[name] is NSNull { return nil }
        return try string(root, name, maximumBytes: maximumBytes)
    }

    private static func boolean(_ root: [String: Any], _ name: String) throws -> Bool {
        guard let value = root[name] as? NSNumber,
              CFGetTypeID(value) == CFBooleanGetTypeID() else {
            throw invalid("\(name) must be a boolean.")
        }
        return value.boolValue
    }

    private static func integer(_ root: [String: Any], _ name: String) throws -> UInt64 {
        guard let value = root[name] as? NSNumber,
              CFGetTypeID(value) != CFBooleanGetTypeID(),
              ["c", "s", "i", "l", "q", "C", "S", "I", "L", "Q"]
                .contains(String(cString: value.objCType)),
              value.int64Value >= 0 else {
            throw invalid("\(name) must be a non-negative integer.")
        }
        return value.uint64Value
    }

    private static func positiveEpoch(
        _ root: [String: Any],
        _ name: String
    ) throws -> UInt64 {
        let value = try integer(root, name)
        guard value > 0, value < UInt64(Int64.max) else {
            throw invalid("\(name) must be positive and below the reserved maximum.")
        }
        return value
    }

    private static func base64(
        _ root: [String: Any],
        _ name: String,
        sizes: ClosedRange<Int>
    ) throws -> Data {
        let encoded = try string(root, name, maximumBytes: 8_192)
        guard let decoded = Data(base64Encoded: encoded), sizes.contains(decoded.count) else {
            throw invalid("\(name) is not valid bounded base64.")
        }
        return decoded
    }

    private static func validateSignalingURL(
        _ value: String,
        allowInsecure: Bool
    ) throws {
        guard let components = URLComponents(string: value),
              let scheme = components.scheme?.lowercased(),
              let host = components.host, !host.isEmpty,
              components.user == nil, components.password == nil,
              components.query == nil, components.fragment == nil else {
            throw invalid("Signaling URL is invalid.")
        }
        let loopback = ["localhost", "127.0.0.1", "::1"].contains(host)
        if allowInsecure {
            guard scheme == "http", loopback else {
                throw invalid("Insecure signaling is limited to explicit loopback testing.")
            }
        } else if scheme != "https" {
            throw invalid("Production signaling requires HTTPS.")
        }
    }

    private static func validateICE(
        urls: [String],
        username: String?,
        credential: String?
    ) throws {
        var containsTURN = false
        for raw in urls {
            guard let url = URL(string: raw),
                  let scheme = url.scheme?.lowercased(),
                  ["stun", "stuns", "turn", "turns"].contains(scheme) else {
                throw invalid("ICE URL scheme is invalid.")
            }
            containsTURN = containsTURN || scheme == "turn" || scheme == "turns"
        }
        guard !containsTURN || (username != nil && credential != nil) else {
            throw invalid("TURN servers require username and credential.")
        }
    }

    private static func invalid(_ reason: String) -> InternetSessionLeaseIssuerError {
        .invalidInput(reason)
    }
}

enum InternetSessionLeaseIssuer {
    typealias StateStoreFactory = (String) -> any SecurityStateStore

    static func issue(
        unsignedJSON: Data,
        now: () -> Date = Date.init,
        validFor lifetime: TimeInterval = 300,
        identityStore: KeychainDeviceIdentityStore = KeychainDeviceIdentityStore(),
        secretStore: any InternetPairingSecretStore = KeychainSecretStore(),
        stateStoreFactory: StateStoreFactory = {
            KeychainSecurityStateStore(peerID: "lease-authority.\($0)")
        }
    ) throws -> Data {
        guard lifetime > 0, lifetime <= 600 else {
            throw InternetSessionLeaseIssuerError.invalidInput(
                "Internet lease lifetime must be between 1 and 600 seconds."
            )
        }
        let requested = try InternetSessionLeaseCodec.decodeUnsigned(unsignedJSON)
        let stateStore = stateStoreFactory(requested.pairingIdentifier)
        let lifecycle = SecurityLifecycle(store: stateStore)
        try lifecycle.requirePairingBinding(requested.pairingIdentifier)
        let identityBindingName = try PairedHostIdentityBinding.keychainName(
            pairingIdentifier: requested.pairingIdentifier
        )
        guard let encodedIdentityBinding = try secretStore.load(name: identityBindingName) else {
            throw InternetSessionLeaseIssuerError.pairedHostIdentityUnavailable
        }
        let identityBinding = try PairedHostIdentityBinding.decode(encodedIdentityBinding)
        guard identityBinding.deviceID == requested.pinnedHostID,
              identityBinding.keyEpoch == requested.hostIdentityEpoch else {
            throw PlatformSecurityError.persistenceFailure(
                "The session lease host identity binding does not match the requested device or key epoch. Pair again."
            )
        }
        let peerIdentityBindingName = try PairedPeerIdentityBinding.keychainName(
            pairingIdentifier: requested.pairingIdentifier
        )
        guard let encodedPeerIdentityBinding = try secretStore.load(
            name: peerIdentityBindingName
        ) else {
            throw InternetSessionLeaseIssuerError.invalidInput(
                "The paired device identity binding is unavailable. Pair again before issuing a session lease."
            )
        }
        let peerIdentityBinding = try PairedPeerIdentityBinding.decode(
            encodedPeerIdentityBinding
        )
        guard peerIdentityBinding.identity.deviceID == requested.pinnedDeviceID,
              peerIdentityBinding.identity.keyID == requested.leaseDeviceKeyID,
              peerIdentityBinding.identity.keyEpoch == requested.deviceIdentityEpoch else {
            throw PlatformSecurityError.persistenceFailure(
                "The session lease device identity epoch does not match the paired device. Pair again."
            )
        }
        let identity = try identityStore.loadVerifiedExisting(binding: identityBinding)
        let epoch = try lifecycle.advanceSessionEpoch()
        let nowSeconds = now().timeIntervalSince1970
        guard nowSeconds >= 0,
              nowSeconds + lifetime < TimeInterval(UInt64(Int64.max)) else {
            throw InternetSessionLeaseIssuerError.invalidInput(
                "Internet lease expiry is outside the supported range."
            )
        }
        let payload = requested.authorizing(
            epoch: epoch,
            expiresAtUnixSeconds: UInt64(nowSeconds + lifetime)
        )
        let digest = InternetSessionLeaseCodec.digest(
            payload,
            leaseHostKeyID: identity.publicIdentity.keyID
        )
        let signature = try identity.signTranscriptDigest(digest)
        return try InternetSessionLeaseCodec.encodeSigned(
            payload,
            leaseHostKeyID: identity.publicIdentity.keyID,
            signature: signature
        )
    }
}

enum InternetSessionLeaseCLI {
    static func run() -> Bool {
        do {
            let input = FileHandle.standardInput.readDataToEndOfFile()
            let output = try InternetSessionLeaseIssuer.issue(unsignedJSON: input)
            FileHandle.standardOutput.write(output)
            FileHandle.standardOutput.write(Data([0x0a]))
            return true
        } catch {
            let message = "Internet lease issuance failed: \(error.localizedDescription)\n"
            FileHandle.standardError.write(Data(message.utf8))
            return false
        }
    }
}

enum InternetSessionLeaseSelfTest {
    static func run() -> Bool {
        do {
            let peerKey = P256.Signing.PrivateKey()
            let peerPublicKey = peerKey.publicKey.x963Representation
            let peerKeyID = Data(SHA256.hash(data: peerPublicKey)).hex
            let leaseJSON = fixtureJSON.replacingOccurrences(
                of: "3d72b4d5f8a0f3f5ef9c3aef38f8a80dcf691f19877005e4d874a998441cb2be",
                with: peerKeyID
            )
            let fixture = try InternetSessionLeaseCodec.decodeUnsigned(
                Data(leaseJSON.utf8)
            )
            let digest = InternetSessionLeaseCodec.digest(
                fixture,
                leaseHostKeyID: "host-key-id"
            )
            let key = P256.Signing.PrivateKey()
            let signature = try rawDigestSignature(privateKey: key, digest: digest)
            let doubleHashedSignature = try key.signature(for: digest).derRepresentation
            guard InternetPairingCanonical.verify(
                signature: signature,
                digest: digest,
                publicKey: key.publicKey.x963Representation
            ), !InternetPairingCanonical.verify(
                signature: doubleHashedSignature,
                digest: digest,
                publicKey: key.publicKey.x963Representation
            ) else { return false }

            let keychainService =
                "dev.telemachus.display.phase3-lease-self-test.\(UUID().uuidString)"
            let keychainStore = KeychainDeviceIdentityStore(
                service: keychainService
            )
            let keychainIdentity = try keychainStore.createIfMissing(
                deviceID: fixture.pinnedHostID
            )
            let bindingStore = KeychainSecretStore(service: "\(keychainService).bindings")
            let peerIdentity = PlatformPublicIdentity(
                deviceID: fixture.pinnedDeviceID,
                keyID: fixture.leaseDeviceKeyID,
                keyEpoch: fixture.deviceIdentityEpoch,
                signingPublicKey: peerPublicKey
            )
            for pairingIdentifier in ["pair-1", "pair-2"] {
                try bindingStore.persist(
                    name: PairedHostIdentityBinding.keychainName(
                        pairingIdentifier: pairingIdentifier
                    ),
                    secret: PairedHostIdentityBinding.encode(
                        keychainIdentity.publicIdentity
                    )
                )
                try bindingStore.persist(
                    name: PairedPeerIdentityBinding.keychainName(
                        pairingIdentifier: pairingIdentifier
                    ),
                    secret: PairedPeerIdentityBinding.encode(peerIdentity)
                )
            }
            let leaseStateStore = SelfTestLeaseStateStore()
            let otherPairingStateStore = SelfTestLeaseStateStore()
            let leaseStateStoreFactory: InternetSessionLeaseIssuer.StateStoreFactory = { pairingIdentifier in
                pairingIdentifier == "pair-1" ? leaseStateStore : otherPairingStateStore
            }
            let signedJSON = try InternetSessionLeaseIssuer.issue(
                unsignedJSON: Data(leaseJSON.utf8),
                identityStore: keychainStore,
                secretStore: bindingStore,
                stateStoreFactory: leaseStateStoreFactory
            )
            guard let signedRoot = try JSONSerialization.jsonObject(
                with: signedJSON
            ) as? [String: Any],
                  let issuedEpoch = (signedRoot["session_epoch"] as? NSNumber)?.uint64Value,
                  let expiresAt = (signedRoot["expires_at"] as? NSNumber)?.uint64Value,
                  issuedEpoch == 1,
                  signedRoot["lease_host_key_id"] as? String ==
                    keychainIdentity.publicIdentity.keyID,
                  let encodedKeychainSignature =
                    signedRoot["lease_signature"] as? String,
                  let keychainSignature = Data(
                    base64Encoded: encodedKeychainSignature
                  ),
                  InternetSessionLeaseCodec.verifyDigestSignature(
                    keychainSignature,
                    digest: InternetSessionLeaseCodec.digest(
                        fixture.authorizing(
                            epoch: issuedEpoch,
                            expiresAtUnixSeconds: expiresAt
                        ),
                        leaseHostKeyID: keychainIdentity.publicIdentity.keyID
                    ),
                    publicKey: keychainIdentity.publicIdentity.signingPublicKey
                  ) else { return false }

            let highCallerJSON = leaseJSON.replacingOccurrences(
                of: "\"session_epoch\":7",
                with: "\"session_epoch\":9223372036854775806"
            )
            let restarted = try InternetSessionLeaseIssuer.issue(
                unsignedJSON: Data(highCallerJSON.utf8),
                identityStore: keychainStore,
                secretStore: bindingStore,
                stateStoreFactory: leaseStateStoreFactory
            )
            guard try signedEpoch(restarted) == 2 else { return false }

            let resultLock = NSLock()
            var concurrentEpochs: [UInt64] = []
            var concurrentFailures = 0
            DispatchQueue.concurrentPerform(iterations: 8) { _ in
                do {
                    let issued = try InternetSessionLeaseIssuer.issue(
                        unsignedJSON: Data(leaseJSON.utf8),
                        identityStore: keychainStore,
                        secretStore: bindingStore,
                        stateStoreFactory: leaseStateStoreFactory
                    )
                    let epoch = try signedEpoch(issued)
                    resultLock.lock(); concurrentEpochs.append(epoch); resultLock.unlock()
                } catch {
                    resultLock.lock(); concurrentFailures += 1; resultLock.unlock()
                }
            }
            guard concurrentFailures == 0,
                  Set(concurrentEpochs) == Set(UInt64(3)...UInt64(10)) else { return false }

            let missingDurableState = SelfTestPairingValidationFailureStore()
            let unreadCredentials = SelfTestCountingLeaseSecretStore()
            do {
                _ = try InternetSessionLeaseIssuer.issue(
                    unsignedJSON: Data(leaseJSON.utf8),
                    identityStore: keychainStore,
                    secretStore: unreadCredentials,
                    stateStoreFactory: { _ in missingDurableState }
                )
                return false
            } catch {}
            guard missingDurableState.validationCalls == 1,
                  missingDurableState.sessionEpoch == 0,
                  unreadCredentials.loadCalls == 0 else { return false }

            let missingBindingState = SelfTestLeaseStateStore()
            do {
                _ = try InternetSessionLeaseIssuer.issue(
                    unsignedJSON: Data(leaseJSON.utf8),
                    identityStore: keychainStore,
                    secretStore: SelfTestLeaseSecretStore(),
                    stateStoreFactory: { _ in missingBindingState }
                )
                return false
            } catch {}
            guard missingBindingState.sessionEpoch == 0 else { return false }

            let mismatchedBindingStore = SelfTestLeaseSecretStore()
            let mismatchedKey = P256.Signing.PrivateKey()
            let mismatchedPublicKey = mismatchedKey.publicKey.x963Representation
            let mismatchedIdentity = PlatformPublicIdentity(
                deviceID: fixture.pinnedHostID,
                keyID: Data(SHA256.hash(data: mismatchedPublicKey))
                    .map { String(format: "%02x", $0) }
                    .joined(),
                keyEpoch: fixture.hostIdentityEpoch,
                signingPublicKey: mismatchedPublicKey
            )
            try mismatchedBindingStore.persist(
                name: PairedHostIdentityBinding.keychainName(
                    pairingIdentifier: fixture.pairingIdentifier
                ),
                secret: PairedHostIdentityBinding.encode(mismatchedIdentity)
            )
            let mismatchState = SelfTestLeaseStateStore()
            do {
                _ = try InternetSessionLeaseIssuer.issue(
                    unsignedJSON: Data(leaseJSON.utf8),
                    identityStore: keychainStore,
                    secretStore: mismatchedBindingStore,
                    stateStoreFactory: { _ in mismatchState }
                )
                return false
            } catch {}
            guard mismatchState.sessionEpoch == 0 else { return false }

            let missingAliasService = "\(keychainService).missing-alias"
            let missingAliasStore = KeychainDeviceIdentityStore(service: missingAliasService)
            let missingAliasIdentity = try missingAliasStore.createIfMissing(
                deviceID: fixture.pinnedHostID
            )
            let missingAliasBindingStore = SelfTestLeaseSecretStore()
            try missingAliasBindingStore.persist(
                name: PairedHostIdentityBinding.keychainName(
                    pairingIdentifier: fixture.pairingIdentifier
                ),
                secret: PairedHostIdentityBinding.encode(
                    missingAliasIdentity.publicIdentity
                )
            )
            try missingAliasStore.delete(deviceID: fixture.pinnedHostID, keyEpoch: 1)
            let missingAliasState = SelfTestLeaseStateStore()
            do {
                _ = try InternetSessionLeaseIssuer.issue(
                    unsignedJSON: Data(leaseJSON.utf8),
                    identityStore: missingAliasStore,
                    secretStore: missingAliasBindingStore,
                    stateStoreFactory: { _ in missingAliasState }
                )
                return false
            } catch {}
            guard missingAliasState.sessionEpoch == 0 else { return false }

            let otherPairingJSON = leaseJSON.replacingOccurrences(
                of: "\"pairing_id\":\"pair-1\"",
                with: "\"pairing_id\":\"pair-2\""
            )
            let otherPairingLease = try InternetSessionLeaseIssuer.issue(
                unsignedJSON: Data(otherPairingJSON.utf8),
                identityStore: keychainStore,
                secretStore: bindingStore,
                stateStoreFactory: leaseStateStoreFactory
            )
            guard try signedEpoch(otherPairingLease) == 1 else { return false }

            let cipherLifecycle = SecurityLifecycle(store: leaseStateStore)
            let stalePair = try PlatformSessionPacketCipher.selfTestPair(
                sessionIdentifier: "lease-self-test-epoch-10",
                sharedSecret: Data(repeating: 0x41, count: 32),
                bootstrapSecret: Data(repeating: 0x42, count: 32),
                transcriptContext: Data(repeating: 0x43, count: 32),
                sessionEpoch: 10,
                requireActiveEpoch: cipherLifecycle.requireCurrentSessionEpoch
            )
            let staleRecord = try stalePair.device.seal(Data("epoch-10".utf8), channel: .control)
            guard stalePair.host.open(staleRecord, channel: .control) != nil,
                  try cipherLifecycle.advanceSessionEpoch() == 11 else { return false }
            let staleSealRejected: Bool
            do {
                _ = try stalePair.device.seal(Data("must-fail".utf8), channel: .control)
                staleSealRejected = false
            } catch {
                staleSealRejected = true
            }
            guard staleSealRejected,
                  stalePair.host.open(staleRecord, channel: .control) == nil else { return false }
            guard try atomicEpochOpenInterleaving() else { return false }

            let mutations = [
                ("\"pairing_id\":\"pair-1\"", "\"pairing_id\":\"pair-2\""),
                ("\"pinned_host_id\":\"host-1\"", "\"pinned_host_id\":\"host-2\""),
                ("https://signal.example.test", "https://other.example.test"),
                ("\"signaling_session_id\":\"session-7\"", "\"signaling_session_id\":\"session-8\""),
                ("\"session_epoch\":7", "\"session_epoch\":8"),
                ("\"device_identity_epoch\":1", "\"device_identity_epoch\":2"),
                ("AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE=", "AgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgI="),
                ("cHJvdG9jb2wtc2Vzc2lvbi03", "b3RoZXItcHJvdG9jb2w="),
                ("device-token-abcdefghijklmnopqrstuvwxyz", "z-device-token-abcdefghijklmnopqrstuvwx"),
                ("stun:stun.example.test", "stun:other.example.test"),
                ("turn-user", "changed-user"),
                ("turn-password", "changed-password")
            ]
            for (original, replacement) in mutations {
                let mutated = leaseJSON.replacingOccurrences(
                    of: original,
                    with: replacement
                )
                let mutatedPayload = try InternetSessionLeaseCodec.decodeUnsigned(
                    Data(mutated.utf8)
                )
                let mutatedDigest = InternetSessionLeaseCodec.digest(
                    mutatedPayload,
                    leaseHostKeyID: "host-key-id"
                )
                guard mutatedDigest != digest,
                      !InternetPairingCanonical.verify(
                        signature: signature,
                        digest: mutatedDigest,
                        publicKey: key.publicKey.x963Representation
                      ) else { return false }
            }
            let changedHostKeyDigest = InternetSessionLeaseCodec.digest(
                fixture,
                leaseHostKeyID: "different-host-key-id"
            )
            let insecureMutation = leaseJSON
                .replacingOccurrences(
                    of: "https://signal.example.test",
                    with: "http://127.0.0.1:8088"
                )
                .replacingOccurrences(
                    of: "\"allow_insecure_for_testing\":false",
                    with: "\"allow_insecure_for_testing\":true"
                )
            let insecurePayload = try InternetSessionLeaseCodec.decodeUnsigned(
                Data(insecureMutation.utf8)
            )
            guard changedHostKeyDigest != digest,
                  InternetSessionLeaseCodec.digest(
                    insecurePayload,
                    leaseHostKeyID: "host-key-id"
                  ) != digest else { return false }

            guard rejects(leaseJSON.dropLast() + ",\"extra\":true}"),
                  rejects(leaseJSON.replacingOccurrences(
                    of: "\"session_epoch\":7",
                    with: "\"session_epoch\":9223372036854775807"
                  )),
                  rejects(leaseJSON.replacingOccurrences(
                    of: "\"credential\":\"turn-password\"",
                    with: "\"credential\":false"
                  )) else { return false }
            try keychainStore.delete(
                deviceID: fixture.pinnedHostID,
                keyEpoch: 1
            )
            for pairingIdentifier in ["pair-1", "pair-2"] {
                try bindingStore.delete(
                    name: PairedHostIdentityBinding.keychainName(
                        pairingIdentifier: pairingIdentifier
                    )
                )
            }
            print("Phase 3 Internet lease self-test: PASS (canonicalKAT=true, mutation=true, strictParser=true, keychainSigner=true, identityBinding=true, missingAliasFailClosed=true, legacyBindingFailClosed=true, missingDurableStateFailClosed=true, stateBeforeCredentials=true, epochUnchangedOnIdentityFailure=true, durableEpochAuthority=true, pairingScopedEpoch=true, staleCipherFailClosed=true, atomicEpochOpen=true)")
            return true
        } catch {
            print("Phase 3 Internet lease self-test: FAIL")
            return false
        }
    }

    private static func rejects(_ value: String) -> Bool {
        do {
            _ = try InternetSessionLeaseCodec.decodeUnsigned(Data(value.utf8))
            return false
        } catch { return true }
    }

    private static func rawDigestSignature(
        privateKey: P256.Signing.PrivateKey,
        digest: Data
    ) throws -> Data {
        guard digest.count == SHA256.byteCount else {
            throw InternetSessionLeaseIssuerError.invalidInput(
                "Lease self-test signing requires a SHA-256 digest."
            )
        }
        let attributes: [String: Any] = [
            kSecAttrKeyType as String: kSecAttrKeyTypeECSECPrimeRandom,
            kSecAttrKeyClass as String: kSecAttrKeyClassPrivate,
            kSecAttrKeySizeInBits as String: 256
        ]
        guard let key = SecKeyCreateWithData(
            privateKey.x963Representation as CFData,
            attributes as CFDictionary,
            nil
        ) else {
            throw InternetSessionLeaseIssuerError.invalidInput(
                "Lease self-test P-256 key is invalid."
            )
        }
        var error: Unmanaged<CFError>?
        guard let signature = SecKeyCreateSignature(
            key,
            .ecdsaSignatureDigestX962SHA256,
            digest as CFData,
            &error
        ) as Data? else {
            if let error { throw error.takeRetainedValue() }
            throw InternetSessionLeaseIssuerError.invalidInput(
                "Lease self-test digest signing failed."
            )
        }
        if let error { throw error.takeRetainedValue() }
        return signature
    }

    private static func signedEpoch(_ data: Data) throws -> UInt64 {
        guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let value = root["session_epoch"] as? NSNumber else {
            throw InternetSessionLeaseIssuerError.invalidInput(
                "Signed self-test lease omitted its authoritative epoch."
            )
        }
        return value.uint64Value
    }

    private static func atomicEpochOpenInterleaving() throws -> Bool {
        let store = SelfTestLeaseStateStore()
        let lifecycle = SecurityLifecycle(store: store)
        guard try lifecycle.reserveSessionEpoch(1) == 1 else { return false }
        let shared = Data(repeating: 0x61, count: 32)
        let bootstrap = Data(repeating: 0x62, count: 32)
        let context = Data(repeating: 0x63, count: 32)
        let source = try PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "atomic-open-self-test",
            sharedSecret: shared,
            bootstrapSecret: bootstrap,
            transcriptContext: context,
            sessionEpoch: 1,
            requireActiveEpoch: lifecycle.requireCurrentSessionEpoch
        )
        let record = try source.device.seal(Data("epoch-one".utf8), channel: .control)
        let entered = DispatchSemaphore(value: 0)
        let release = DispatchSemaphore(value: 0)
        let openFinished = DispatchSemaphore(value: 0)
        let reserveStarted = DispatchSemaphore(value: 0)
        let reserveFinished = DispatchSemaphore(value: 0)
        let result = AtomicEpochOpenSelfTestResult()
        let interleaved = try PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "atomic-open-self-test",
            sharedSecret: shared,
            bootstrapSecret: bootstrap,
            transcriptContext: context,
            sessionEpoch: 1,
            withActiveEpoch: { epoch, operation in
                try lifecycle.withActiveSessionEpoch(epoch) {
                    entered.signal()
                    guard release.wait(timeout: .now() + 2) == .success else {
                        throw PlatformSecurityError.persistenceFailure("atomic open latch timed out")
                    }
                    return try operation()
                }
            }
        )
        DispatchQueue.global().async {
            result.setOpened(interleaved.host.open(record, channel: .control))
            openFinished.signal()
        }
        guard entered.wait(timeout: .now() + 2) == .success else { return false }
        DispatchQueue.global().async {
            reserveStarted.signal()
            do { result.setReserved(try lifecycle.reserveSessionEpoch(2)) }
            catch { result.setFailure(error.localizedDescription) }
            reserveFinished.signal()
        }
        guard reserveStarted.wait(timeout: .now() + 2) == .success else {
            release.signal()
            return false
        }
        guard reserveFinished.wait(timeout: .now() + 0.05) == .timedOut else {
            release.signal()
            return false
        }
        release.signal()
        guard openFinished.wait(timeout: .now() + 2) == .success,
              reserveFinished.wait(timeout: .now() + 2) == .success,
              result.opened == Data("epoch-one".utf8),
              result.reserved == 2,
              result.failure == nil else { return false }
        return interleaved.host.open(record, channel: .control) == nil
    }

    private static let fixtureJSON = """
    {"version":1,"pairing_id":"pair-1","pinned_host_id":"host-1","pinned_device_id":"device-1","lease_device_key_id":"LEASE_DEVICE_KEY_ID","signaling_url":"https://signal.example.test","signaling_session_id":"session-7","session_epoch":7,"host_identity_epoch":1,"device_identity_epoch":1,"transcript_context":"AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE=","protocol_session_id":"cHJvdG9jb2wtc2Vzc2lvbi03","signaling_token":"device-token-abcdefghijklmnopqrstuvwxyz","ice_servers":[{"urls":["stun:stun.example.test"],"username":null,"credential":null},{"urls":["turn:turn.example.test"],"username":"turn-user","credential":"turn-password"}],"allow_insecure_for_testing":false}
    """
}

private final class SelfTestLeaseStateStore: SecurityStateStore {
    private var state = PersistedSecurityState()

    var sessionEpoch: UInt64 { state.sessionEpoch }

    func load() throws -> PersistedSecurityState { state }
    func persist(_ state: PersistedSecurityState) throws { self.state = state }
}

private final class SelfTestPairingValidationFailureStore: SecurityStateStore {
    private var state = PersistedSecurityState()
    private(set) var validationCalls = 0

    var sessionEpoch: UInt64 { state.sessionEpoch }

    func load() throws -> PersistedSecurityState { state }
    func persist(_ state: PersistedSecurityState) throws { self.state = state }
    func validatePairingBinding(
        pairingIdentifier _: String
    ) throws -> PersistedSecurityState {
        validationCalls += 1
        throw PlatformSecurityError.persistenceFailure(
            "self-test missing durable pairing state"
        )
    }
}

private final class SelfTestCountingLeaseSecretStore: InternetPairingSecretStore {
    private(set) var loadCalls = 0

    func load(name _: String) throws -> Data? {
        loadCalls += 1
        return nil
    }

    func persist(name _: String, secret _: Data) throws {}
    func delete(name _: String) throws {}
}

private final class SelfTestLeaseSecretStore: InternetPairingSecretStore {
    private var values: [String: Data] = [:]

    func load(name: String) throws -> Data? { values[name] }
    func persist(name: String, secret: Data) throws { values[name] = secret }
    func delete(name: String) throws { values.removeValue(forKey: name) }
}

private final class AtomicEpochOpenSelfTestResult: @unchecked Sendable {
    private let lock = NSLock()
    private var storedOpened: Data?
    private var storedReserved: UInt64?
    private var storedFailure: String?

    var opened: Data? {
        lock.lock()
        defer { lock.unlock() }
        return storedOpened
    }
    var reserved: UInt64? {
        lock.lock()
        defer { lock.unlock() }
        return storedReserved
    }
    var failure: String? {
        lock.lock()
        defer { lock.unlock() }
        return storedFailure
    }
    func setOpened(_ value: Data?) {
        lock.lock()
        storedOpened = value
        lock.unlock()
    }
    func setReserved(_ value: UInt64) {
        lock.lock()
        storedReserved = value
        lock.unlock()
    }
    func setFailure(_ value: String) {
        lock.lock()
        storedFailure = value
        lock.unlock()
    }
}

private extension Data {
    var hex: String { map { String(format: "%02x", $0) }.joined() }
}
