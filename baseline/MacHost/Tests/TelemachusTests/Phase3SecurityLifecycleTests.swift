import CryptoKit
import Foundation
import Security
import XCTest
@testable import Telemachus

final class Phase3SecurityLifecycleTests: XCTestCase {
    private static let childServiceEnvironment = "VIBE_SCREEN_SECURITY_CHILD_SERVICE"
    private static let childAccountEnvironment = "VIBE_SCREEN_SECURITY_CHILD_ACCOUNT"
    private static let childResultEnvironment = "VIBE_SCREEN_SECURITY_CHILD_RESULT"
    private static let counterTestSelector =
        "TelemachusTests.Phase3SecurityLifecycleTests/testKeychainCountersAreUniqueAcrossChildProcesses"

    func testKeychainCountersAreUniqueAcrossChildProcesses() throws {
        if let childConfiguration = childCounterConfiguration() {
            try runCounterChild(configuration: childConfiguration)
            return
        }

        let service = "dev.vibescreen.cross-process-security.\(UUID().uuidString)"
        let account = "shared-state"
        let temporaryDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("vibe-screen-security-processes-\(UUID().uuidString)")
        try FileManager.default.createDirectory(
            at: temporaryDirectory,
            withIntermediateDirectories: true
        )
        let gateURL = temporaryDirectory.appendingPathComponent("start")
        let childCount = 8
        var children: [(process: Process, resultURL: URL, output: Pipe, error: Pipe)] = []
        defer {
            for child in children where child.process.isRunning {
                child.process.terminate()
                child.process.waitUntilExit()
            }
            try? FileManager.default.removeItem(at: temporaryDirectory)
            try? KeychainSecretStore(service: service).delete(name: account)
        }

        for index in 0..<childCount {
            let resultURL = temporaryDirectory.appendingPathComponent("result-\(index).json")
            let process = Process()
            let output = Pipe()
            let error = Pipe()
            var environment = ProcessInfo.processInfo.environment
            environment[Self.childServiceEnvironment] = service
            environment[Self.childAccountEnvironment] = account
            environment[Self.childResultEnvironment] = resultURL.path
            process.environment = environment
            process.executableURL = URL(fileURLWithPath: "/bin/sh")
            process.arguments = [
                "-c",
                "while [ ! -e \"$1\" ]; do sleep 0.01; done; exec /usr/bin/xcrun xctest -XCTest \"$2\" \"$3\"",
                "security-process-test",
                gateURL.path,
                Self.counterTestSelector,
                Bundle(for: Self.self).bundleURL.path
            ]
            process.standardOutput = output
            process.standardError = error
            try process.run()
            children.append((process, resultURL, output, error))
        }
        try Data().write(to: gateURL, options: .atomic)

        var epochs: Set<UInt64> = []
        var nonces: Set<Data> = []
        for child in children {
            child.process.waitUntilExit()
            let output = child.output.fileHandleForReading.readDataToEndOfFile()
            let error = child.error.fileHandleForReading.readDataToEndOfFile()
            XCTAssertEqual(
                child.process.terminationStatus,
                0,
                String(decoding: output, as: UTF8.self)
                    + String(decoding: error, as: UTF8.self)
            )
            guard child.process.terminationStatus == 0 else { continue }
            let result = try JSONSerialization.jsonObject(
                with: Data(contentsOf: child.resultURL)
            ) as? [String: Any]
            let epoch = try XCTUnwrap((result?["epoch"] as? NSNumber)?.uint64Value)
            let encodedNonce = try XCTUnwrap(result?["nonce"] as? String)
            let nonce = try XCTUnwrap(Data(base64Encoded: encodedNonce))
            XCTAssertEqual(nonce.count, 12)
            epochs.insert(epoch)
            nonces.insert(nonce)
        }
        XCTAssertEqual(epochs, Set(UInt64(1)...UInt64(childCount)))
        XCTAssertEqual(nonces.count, childCount)
    }

    private func childCounterConfiguration() -> (service: String, account: String, resultURL: URL)? {
        let environment = ProcessInfo.processInfo.environment
        guard let service = environment[Self.childServiceEnvironment],
              let account = environment[Self.childAccountEnvironment],
              let resultPath = environment[Self.childResultEnvironment] else {
            return nil
        }
        return (service, account, URL(fileURLWithPath: resultPath))
    }

    private func runCounterChild(
        configuration: (service: String, account: String, resultURL: URL)
    ) throws {
        let lifecycle = SecurityLifecycle(
            store: KeychainSecurityStateStore(
                service: configuration.service,
                account: configuration.account
            )
        )
        let epoch = try lifecycle.advanceSessionEpoch()
        let nonce = try lifecycle.reserveNonce(
            channel: 1,
            senderRole: 1,
            keyEpoch: 1
        )
        let result: [String: Any] = [
            "epoch": epoch,
            "nonce": nonce.base64EncodedString()
        ]
        try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
            .write(to: configuration.resultURL, options: .atomic)
    }

    func testCommittedPairingBindingRollsBackFailedRepairAndFinalizesSuccess() throws {
        let service = "dev.vibescreen.repair-binding.\(UUID().uuidString)"
        let store = KeychainSecurityStateStore(
            peerID: "repair-peer",
            service: service,
            legacyAccount: nil,
            legacyCleanupAccount: nil
        )
        try store.initializePairingBinding(pairingIdentifier: "pairing-old")
        var state = try store.validatePairingBinding(
            pairingIdentifier: "pairing-old"
        )
        state.sessionEpoch = 9
        try store.persist(state)

        try store.initializePairingBinding(pairingIdentifier: "pairing-new")
        XCTAssertEqual(
            try store.validatePairingBinding(
                pairingIdentifier: "pairing-new"
            ).sessionEpoch,
            9
        )
        try store.rollbackPairingBinding(pairingIdentifier: "pairing-new")
        XCTAssertEqual(
            try store.validatePairingBinding(
                pairingIdentifier: "pairing-old"
            ).sessionEpoch,
            9
        )

        try store.initializePairingBinding(pairingIdentifier: "pairing-new")
        try store.finalizePairingBinding(pairingIdentifier: "pairing-new")
        XCTAssertThrowsError(
            try store.validatePairingBinding(pairingIdentifier: "pairing-old")
        )
        XCTAssertEqual(
            try store.validatePairingBinding(
                pairingIdentifier: "pairing-new"
            ).sessionEpoch,
            9
        )
        try store.deleteCommittedPairingBinding(pairingIdentifier: "pairing-new")
    }

    func testSessionEpochIsPersistedBeforeItIsReturned() throws {
        let store = MemorySecurityStateStore()
        XCTAssertEqual(try SecurityLifecycle(store: store).beginSession(), 1)

        let afterRestart = SecurityLifecycle(store: store)
        XCTAssertEqual(try afterRestart.beginSession(), 2)
        XCTAssertEqual(store.state.sessionEpoch, 2)
    }

    func testAuthorityEpochMustFitAndroidSignedLong() throws {
        let store = MemorySecurityStateStore()
        XCTAssertThrowsError(
            try SecurityLifecycle(store: store).reserveSessionEpoch(UInt64(Int64.max) + 1)
        )
        XCTAssertEqual(store.state.sessionEpoch, 0)
        XCTAssertEqual(
            try SecurityLifecycle(store: store).reserveSessionEpoch(UInt64(Int64.max)),
            UInt64(Int64.max)
        )
    }

    func testLegacyMigrationCopiesOnlyCrashSafetyWatermarks() throws {
        let legacy = PersistedSecurityState(
            sessionEpoch: 9,
            revocationSequence: 4,
            revoked: false,
            nonceHighWatermarks: ["1:1:1": 7],
            usedRotationNonceHashes: [String(repeating: "a", count: 64)]
        )
        let migrated = try KeychainSecurityStateStore.migratedLegacyState(legacy)

        XCTAssertEqual(migrated.sessionEpoch, 9)
        XCTAssertEqual(migrated.nonceHighWatermarks, ["1:1:1": 7])
        XCTAssertEqual(migrated.revocationSequence, 0)
        XCTAssertFalse(migrated.revoked)
        XCTAssertNil(migrated.peerRevocation)
        XCTAssertTrue(migrated.usedRotationNonceHashes.isEmpty)
    }

    func testLegacyRevocationRequiresExplicitMigration() {
        let legacy = PersistedSecurityState(revocationSequence: 1, revoked: true)
        XCTAssertThrowsError(try KeychainSecurityStateStore.migratedLegacyState(legacy))
    }

    func testUnpairedKeychainStateMayInitializeOnce() throws {
        let fixture = KeychainPairingStateFixture()
        defer { fixture.cleanup() }

        XCTAssertEqual(try fixture.store.load(), PersistedSecurityState())
        try fixture.store.initializePairingBinding(
            pairingIdentifier: fixture.pairingIdentifier
        )
        XCTAssertEqual(
            try fixture.store.validatePairingBinding(
                pairingIdentifier: fixture.pairingIdentifier
            ),
            PersistedSecurityState()
        )
    }

    func testPairingBindingRejectsMissingOrCorruptDurableState() throws {
        let fixture = KeychainPairingStateFixture()
        defer { fixture.cleanup() }
        try fixture.store.initializePairingBinding(
            pairingIdentifier: fixture.pairingIdentifier
        )

        try fixture.rawStore.delete(name: fixture.store.account)
        XCTAssertThrowsError(
            try fixture.store.validatePairingBinding(
                pairingIdentifier: fixture.pairingIdentifier
            )
        ) { error in
            XCTAssertTrue(error.localizedDescription.contains("durable security state is missing"))
        }

        try fixture.rawStore.persist(
            name: fixture.store.account,
            secret: Data("not-json".utf8)
        )
        XCTAssertThrowsError(
            try fixture.store.validatePairingBinding(
                pairingIdentifier: fixture.pairingIdentifier
            )
        ) { error in
            XCTAssertTrue(error.localizedDescription.contains("security state is invalid"))
        }
    }

    func testPairingBindingRejectsMissingCorruptOrWrongOwnerMarker() throws {
        let fixture = KeychainPairingStateFixture()
        defer { fixture.cleanup() }
        try fixture.store.initializePairingBinding(
            pairingIdentifier: fixture.pairingIdentifier
        )
        let bindingAccount = try XCTUnwrap(fixture.store.bindingAccount)

        try fixture.rawStore.delete(name: bindingAccount)
        XCTAssertThrowsError(
            try fixture.store.validatePairingBinding(
                pairingIdentifier: fixture.pairingIdentifier
            )
        ) { error in
            XCTAssertTrue(error.localizedDescription.contains("binding is missing"))
        }

        try fixture.rawStore.persist(
            name: bindingAccount,
            secret: Data("not-json".utf8)
        )
        XCTAssertThrowsError(
            try fixture.store.validatePairingBinding(
                pairingIdentifier: fixture.pairingIdentifier
            )
        ) { error in
            XCTAssertTrue(error.localizedDescription.contains("binding is invalid"))
        }

        try fixture.rawStore.delete(name: bindingAccount)
        try fixture.store.initializePairingBinding(
            pairingIdentifier: fixture.pairingIdentifier
        )
        XCTAssertThrowsError(
            try fixture.store.validatePairingBinding(
                pairingIdentifier: String(repeating: "b", count: 64)
            )
        ) { error in
            XCTAssertTrue(error.localizedDescription.contains("wrong owner"))
        }
    }

    func testPairingBindingPreservesEpochAndNonceHighWatermarks() throws {
        let fixture = KeychainPairingStateFixture()
        defer { fixture.cleanup() }
        try fixture.store.initializePairingBinding(
            pairingIdentifier: fixture.pairingIdentifier
        )
        let lifecycle = SecurityLifecycle(store: fixture.store)
        try lifecycle.requirePairingBinding(fixture.pairingIdentifier)
        XCTAssertEqual(try lifecycle.reserveSessionEpoch(41), 41)
        XCTAssertEqual(
            try lifecycle.reserveNonce(
                sessionEpoch: 41,
                channel: 1,
                senderRole: 1,
                keyEpoch: 1
            ).hex,
            "000000010000000000000001"
        )

        let restarted = KeychainSecurityStateStore(
            peerID: fixture.peerID,
            service: fixture.service,
            legacyAccount: nil,
            legacyCleanupAccount: nil
        )
        let restored = try restarted.validatePairingBinding(
            pairingIdentifier: fixture.pairingIdentifier
        )
        XCTAssertEqual(restored.sessionEpoch, 41)
        XCTAssertEqual(restored.nonceHighWatermarks["1:1:1"], 1)
        XCTAssertThrowsError(try SecurityLifecycle(store: restarted).reserveSessionEpoch(41))

        try fixture.rawStore.delete(name: restarted.account)
        XCTAssertThrowsError(
            try restarted.validatePairingBinding(
                pairingIdentifier: fixture.pairingIdentifier
            )
        )
    }

    func testBoundLifecycleRejectsMarkerLossBeforeNonceReservation() throws {
        let fixture = KeychainPairingStateFixture()
        defer { fixture.cleanup() }
        try fixture.store.initializePairingBinding(
            pairingIdentifier: fixture.pairingIdentifier
        )
        let lifecycle = SecurityLifecycle(store: fixture.store)
        try lifecycle.requirePairingBinding(fixture.pairingIdentifier)
        XCTAssertEqual(try lifecycle.reserveSessionEpoch(3), 3)

        try fixture.rawStore.delete(
            name: try XCTUnwrap(fixture.store.bindingAccount)
        )
        XCTAssertThrowsError(
            try lifecycle.reserveNonce(
                sessionEpoch: 3,
                channel: 1,
                senderRole: 1,
                keyEpoch: 1
            )
        )
        XCTAssertTrue(try fixture.store.load().nonceHighWatermarks.isEmpty)
    }

    func testPairingBindingKeepsRevokedPeerFailClosed() throws {
        let fixture = KeychainPairingStateFixture()
        defer { fixture.cleanup() }
        try fixture.store.initializePairingBinding(
            pairingIdentifier: fixture.pairingIdentifier
        )
        try SecurityLifecycle(store: fixture.store).applyRevocation(sequence: 7)

        XCTAssertThrowsError(
            try SecurityLifecycle(store: fixture.store).requirePairingBinding(
                fixture.pairingIdentifier
            )
        ) { error in
            XCTAssertEqual(error as? PlatformSecurityError, .revoked)
        }
    }

    func testPairingRollbackDeletesNewStateAndAllowsRepair() throws {
        let fixture = KeychainPairingStateFixture()
        defer { fixture.cleanup() }
        try fixture.store.initializePairingBinding(
            pairingIdentifier: fixture.pairingIdentifier
        )
        try SecurityLifecycle(store: fixture.store).reserveSessionEpoch(9)
        try fixture.store.rollbackPairingBinding(
            pairingIdentifier: fixture.pairingIdentifier
        )

        XCTAssertEqual(try fixture.store.load(), PersistedSecurityState())
        XCTAssertThrowsError(
            try fixture.store.validatePairingBinding(
                pairingIdentifier: fixture.pairingIdentifier
            )
        )

        let repairedIdentifier = String(repeating: "c", count: 64)
        try fixture.store.initializePairingBinding(
            pairingIdentifier: repairedIdentifier
        )
        XCTAssertEqual(
            try fixture.store.validatePairingBinding(
                pairingIdentifier: repairedIdentifier
            ),
            PersistedSecurityState()
        )
    }

    func testPairingRollbackPreservesPreexistingHighWatermarks() throws {
        let fixture = KeychainPairingStateFixture()
        defer { fixture.cleanup() }
        let preexisting = PersistedSecurityState(
            sessionEpoch: 27,
            nonceHighWatermarks: ["1:1:1": 19]
        )
        try fixture.store.persist(preexisting)
        try fixture.store.initializePairingBinding(
            pairingIdentifier: fixture.pairingIdentifier
        )
        try fixture.store.rollbackPairingBinding(
            pairingIdentifier: fixture.pairingIdentifier
        )

        XCTAssertEqual(try fixture.store.load(), preexisting)
        XCTAssertThrowsError(
            try fixture.store.validatePairingBinding(
                pairingIdentifier: fixture.pairingIdentifier
            )
        )
    }

    func testStoredSessionValidatesDurableStateBeforeReadingCredentials() throws {
        let stateStore = PairingValidationFailureStore()
        let secretStore = CountingInternetPairingSecretStore()
        let security = PlatformSessionSecurity(
            deviceID: "mac-host",
            peerID: "tablet|key:test",
            stateStore: stateStore
        )
        let pairingIdentifier = String(repeating: "d", count: 64)
        let names = try PairedDeviceSecretNames(
            sharedSecret: "pairing.\(pairingIdentifier).shared.v1",
            bootstrapSecret: "pairing.\(pairingIdentifier).bootstrap.v1",
            identityBinding: PairedHostIdentityBinding.keychainName(
                pairingIdentifier: pairingIdentifier
            ),
            pairingIdentifier: pairingIdentifier
        )

        XCTAssertThrowsError(
            try security.startStoredProtectedInternetSession(
                sessionIdentifier: "state-before-credentials",
                localRole: .host,
                identityEpoch: 1,
                secretNames: names,
                transcriptContext: Data(repeating: 1, count: 32),
                agreedSessionEpoch: 1,
                secretStore: secretStore
            )
        )
        XCTAssertEqual(stateStore.validationCalls, 1)
        XCTAssertEqual(secretStore.loadCalls, 0)
    }

    func testAgreedSessionEpochIsPersistedAndRejectsRollbackOrReuse() throws {
        let store = MemorySecurityStateStore()
        let lifecycle = SecurityLifecycle(store: store)

        XCTAssertEqual(try lifecycle.reserveSessionEpoch(42), 42)
        XCTAssertEqual(store.state.sessionEpoch, 42)
        XCTAssertThrowsError(try SecurityLifecycle(store: store).reserveSessionEpoch(42))
        XCTAssertThrowsError(try SecurityLifecycle(store: store).reserveSessionEpoch(41))
        XCTAssertEqual(try SecurityLifecycle(store: store).advanceSessionEpoch(), 43)
    }

    func testNonceReservationRejectsAStaleSessionEpoch() throws {
        let store = MemorySecurityStateStore()
        let lifecycle = SecurityLifecycle(store: store)
        try lifecycle.reserveSessionEpoch(7)

        XCTAssertNoThrow(
            try lifecycle.reserveNonce(sessionEpoch: 7, channel: 1, senderRole: 1, keyEpoch: 1)
        )
        try lifecycle.reserveSessionEpoch(9)
        XCTAssertThrowsError(
            try lifecycle.reserveNonce(sessionEpoch: 7, channel: 1, senderRole: 1, keyEpoch: 1)
        )
    }

    func testNonceSequenceCannotRepeatAcrossRestart() throws {
        let store = MemorySecurityStateStore()
        let first = try SecurityLifecycle(store: store).reserveNonce(channel: 1, senderRole: 1, keyEpoch: 4)
        let second = try SecurityLifecycle(store: store).reserveNonce(channel: 1, senderRole: 1, keyEpoch: 4)

        XCTAssertEqual(first.hex, "000000010000000000000001")
        XCTAssertEqual(second.hex, "000000010000000000000002")
    }

    func testRevocationFailsClosedAfterRestart() throws {
        let store = MemorySecurityStateStore()
        let lifecycle = SecurityLifecycle(store: store)
        try lifecycle.applyRevocation(sequence: 8)

        XCTAssertThrowsError(try SecurityLifecycle(store: store).beginSession()) { error in
            XCTAssertEqual(error as? PlatformSecurityError, .revoked)
        }
        XCTAssertThrowsError(try lifecycle.applyRevocation(sequence: 8))
    }

    func testSignedPeerRevocationPersistsTargetedTombstone() throws {
        let authorityKey = try TestSigningKey(deviceID: "host", keyEpoch: 1)
        let authority = authorityKey.identity
        let peer = try TestSigningKey(deviceID: "tablet", keyEpoch: 3).identity
        let tombstone = try signedTombstone(
            authorityKey: authorityKey,
            authority: authority,
            peer: peer,
            sequence: 11
        )
        let store = MemorySecurityStateStore()
        let lifecycle = SecurityLifecycle(store: store)

        try lifecycle.applyPeerRevocation(
            tombstone,
            expectedAuthority: authority,
            expectedPeer: peer
        )

        XCTAssertEqual(store.state.peerRevocation, tombstone)
        XCTAssertEqual(store.state.revocationSequence, 11)
        XCTAssertThrowsError(try SecurityLifecycle(store: store).advanceSessionEpoch()) { error in
            XCTAssertEqual(error as? PlatformSecurityError, .revoked)
        }
    }

    func testPeerRevocationRejectsTamperAndSequenceReuse() throws {
        let authorityKey = try TestSigningKey(deviceID: "host", keyEpoch: 1)
        let authority = authorityKey.identity
        let peer = try TestSigningKey(deviceID: "tablet", keyEpoch: 1).identity
        let valid = try signedTombstone(
            authorityKey: authorityKey,
            authority: authority,
            peer: peer,
            sequence: 4
        )
        let tampered = PairedDeviceRevocationTombstone(
            peerIdentity: valid.peerIdentity,
            sequence: valid.sequence,
            revokedAtUnixSeconds: valid.revokedAtUnixSeconds,
            nonce: valid.nonce,
            reasonCode: "tampered",
            authority: valid.authority,
            authoritySignature: valid.authoritySignature
        )
        let store = MemorySecurityStateStore()
        let lifecycle = SecurityLifecycle(store: store)

        XCTAssertThrowsError(
            try lifecycle.applyPeerRevocation(
                tampered,
                expectedAuthority: authority,
                expectedPeer: peer
            )
        )
        XCTAssertNil(store.state.peerRevocation)
        try lifecycle.applyPeerRevocation(valid, expectedAuthority: authority, expectedPeer: peer)
        XCTAssertNoThrow(
            try lifecycle.applyPeerRevocation(valid, expectedAuthority: authority, expectedPeer: peer)
        )
        let conflicting = try signedTombstone(
            authorityKey: authorityKey,
            authority: authority,
            peer: peer,
            sequence: valid.sequence
        )
        XCTAssertThrowsError(
            try lifecycle.applyPeerRevocation(conflicting, expectedAuthority: authority, expectedPeer: peer)
        )
    }

    func testPeerRevocationDeletesOnlyPairedSecretsAfterTombstoneCommit() throws {
        let authorityKey = try TestSigningKey(deviceID: "host", keyEpoch: 1)
        let authority = authorityKey.identity
        let peer = try TestSigningKey(deviceID: "tablet", keyEpoch: 1).identity
        let tombstone = try signedTombstone(
            authorityKey: authorityKey,
            authority: authority,
            peer: peer,
            sequence: 1
        )
        let stateStore = MemorySecurityStateStore()
        let secretStore = MemoryPairedDeviceSecretStore()
        let security = PlatformSessionSecurity(
            deviceID: "mac-host",
            peerID: PairedDeviceSecurityScope.identifier(peer),
            stateStore: stateStore
        )
        let names = try PairedDeviceSecretNames(
            sharedSecret: "tablet.shared",
            bootstrapSecret: "tablet.bootstrap"
        )

        try security.revokePeer(
            tombstone,
            expectedAuthority: authority,
            expectedPeer: peer,
            secretNames: names,
            secretStore: secretStore
        )

        XCTAssertEqual(secretStore.deletedNames, ["tablet.shared", "tablet.bootstrap"])
        XCTAssertEqual(stateStore.state.peerRevocation, tombstone)
        XCTAssertNil(stateStore.state.revocationSecretCleanup)
    }

    func testPeerRevocationRemainsFailClosedWhenSecretDeletionMustRetry() throws {
        let authorityKey = try TestSigningKey(deviceID: "host", keyEpoch: 1)
        let peer = try TestSigningKey(deviceID: "tablet", keyEpoch: 1).identity
        let tombstone = try signedTombstone(
            authorityKey: authorityKey,
            authority: authorityKey.identity,
            peer: peer,
            sequence: 2
        )
        let stateStore = MemorySecurityStateStore()
        let secretStore = MemoryPairedDeviceSecretStore(failingName: "tablet.bootstrap")
        let security = PlatformSessionSecurity(
            deviceID: "mac-host",
            peerID: PairedDeviceSecurityScope.identifier(peer),
            stateStore: stateStore
        )
        let names = try PairedDeviceSecretNames(
            sharedSecret: "tablet.shared",
            bootstrapSecret: "tablet.bootstrap"
        )

        XCTAssertThrowsError(
            try security.revokePeer(
                tombstone,
                expectedAuthority: authorityKey.identity,
                expectedPeer: peer,
                secretNames: names,
                secretStore: secretStore
            )
        )
        XCTAssertEqual(stateStore.state.peerRevocation, tombstone)
        XCTAssertEqual(
            stateStore.state.revocationSecretCleanup?.remainingSecretNames,
            ["tablet.bootstrap"]
        )
        XCTAssertThrowsError(try security.advanceSessionEpoch()) { error in
            XCTAssertEqual(error as? PlatformSecurityError, .revoked)
        }

        secretStore.failingName = nil
        XCTAssertNoThrow(
            try security.revokePeer(
                tombstone,
                expectedAuthority: authorityKey.identity,
                expectedPeer: peer,
                secretNames: names,
                secretStore: secretStore
            )
        )
        XCTAssertEqual(secretStore.deletedNames.last, "tablet.bootstrap")
        XCTAssertNil(stateStore.state.revocationSecretCleanup)
    }

    func testPeerRevocationCleanupAggregatesFailuresAndResumesAfterRestart() throws {
        let authorityKey = try TestSigningKey(deviceID: "host", keyEpoch: 1)
        let peer = try TestSigningKey(deviceID: "tablet", keyEpoch: 1).identity
        let tombstone = try signedTombstone(
            authorityKey: authorityKey,
            authority: authorityKey.identity,
            peer: peer,
            sequence: 3
        )
        let stateStore = MemorySecurityStateStore()
        let secretStore = MemoryPairedDeviceSecretStore(
            failingNames: ["tablet.shared"]
        )
        let peerID = PairedDeviceSecurityScope.identifier(peer)
        let names = try PairedDeviceSecretNames(
            sharedSecret: "tablet.shared",
            bootstrapSecret: "tablet.bootstrap"
        )

        XCTAssertThrowsError(
            try PlatformSessionSecurity(
                deviceID: "mac-host",
                peerID: peerID,
                stateStore: stateStore
            ).revokePeer(
                tombstone,
                expectedAuthority: authorityKey.identity,
                expectedPeer: peer,
                secretNames: names,
                secretStore: secretStore
            )
        )
        XCTAssertEqual(
            secretStore.attemptedNames,
            ["tablet.shared", "tablet.bootstrap"],
            "A shared-secret failure must not skip bootstrap-secret cleanup."
        )
        XCTAssertEqual(secretStore.deletedNames, ["tablet.bootstrap"])
        XCTAssertEqual(
            stateStore.state.revocationSecretCleanup?.remainingSecretNames,
            ["tablet.shared"]
        )

        let afterRestart = PlatformSessionSecurity(
            deviceID: "mac-host",
            peerID: peerID,
            stateStore: stateStore
        )
        XCTAssertTrue(try afterRestart.hasPendingRevocationSecretCleanup())
        secretStore.failingNames = []
        try afterRestart.retryRevocationSecretCleanup(secretStore: secretStore)

        XCTAssertFalse(try afterRestart.hasPendingRevocationSecretCleanup())
        XCTAssertNil(stateStore.state.revocationSecretCleanup)
        XCTAssertEqual(secretStore.deletedNames.last, "tablet.shared")
    }

    func testCleanupProgressPersistenceFailureKeepsMarkerForRestart() throws {
        let authorityKey = try TestSigningKey(deviceID: "host", keyEpoch: 1)
        let peer = try TestSigningKey(deviceID: "tablet", keyEpoch: 1).identity
        let tombstone = try signedTombstone(
            authorityKey: authorityKey,
            authority: authorityKey.identity,
            peer: peer,
            sequence: 4
        )
        let stateStore = MemorySecurityStateStore()
        // Call 1 atomically commits tombstone + marker. Call 2 attempts to
        // remove the already-deleted shared secret from that marker.
        stateStore.failPersistCalls = [2]
        let secretStore = MemoryPairedDeviceSecretStore()
        let peerID = PairedDeviceSecurityScope.identifier(peer)

        XCTAssertThrowsError(
            try PlatformSessionSecurity(
                deviceID: "mac-host",
                peerID: peerID,
                stateStore: stateStore
            ).revokePeer(
                tombstone,
                expectedAuthority: authorityKey.identity,
                expectedPeer: peer,
                secretNames: try PairedDeviceSecretNames(
                    sharedSecret: "tablet.shared",
                    bootstrapSecret: "tablet.bootstrap"
                ),
                secretStore: secretStore
            )
        )
        XCTAssertEqual(secretStore.deletedNames, ["tablet.shared", "tablet.bootstrap"])
        XCTAssertEqual(
            stateStore.state.revocationSecretCleanup?.remainingSecretNames,
            ["tablet.shared"]
        )

        let afterRestart = PlatformSessionSecurity(
            deviceID: "mac-host",
            peerID: peerID,
            stateStore: stateStore
        )
        try afterRestart.retryRevocationSecretCleanup(secretStore: secretStore)
        XCTAssertNil(stateStore.state.revocationSecretCleanup)
        XCTAssertEqual(secretStore.deletedNames.last, "tablet.shared")
    }

    func testPeerScopedKeychainAccountsAreDistinctAndDoNotExposePeerID() {
        let first = KeychainSecurityStateStore.accountName(peerID: "tablet-a")
        let second = KeychainSecurityStateStore.accountName(peerID: "tablet-b")

        XCTAssertNotEqual(first, second)
        XCTAssertTrue(first.hasPrefix("durable-state-v2.peer."))
        XCTAssertFalse(first.contains("tablet-a"))
        XCTAssertNotEqual(first, "durable-state-v1")
    }

    func testRevocationScopeDistinguishesNewSigningIdentityForSameDeviceID() {
        let oldIdentity = PlatformPublicIdentity(
            deviceID: "tablet",
            keyID: String(repeating: "a", count: 64),
            keyEpoch: 1,
            signingPublicKey: Data([UInt8(0x04)] + Array(repeating: UInt8(1), count: 64))
        )
        let newIdentity = PlatformPublicIdentity(
            deviceID: "tablet",
            keyID: String(repeating: "b", count: 64),
            keyEpoch: 2,
            signingPublicKey: Data([UInt8(0x04)] + Array(repeating: UInt8(2), count: 64))
        )

        XCTAssertNotEqual(
            PairedDeviceSecurityScope.identifier(oldIdentity),
            PairedDeviceSecurityScope.identifier(newIdentity)
        )
        XCTAssertNotEqual(
            KeychainSecurityStateStore.accountName(
                peerID: PairedDeviceSecurityScope.identifier(oldIdentity)
            ),
            KeychainSecurityStateStore.accountName(
                peerID: PairedDeviceSecurityScope.identifier(newIdentity)
            )
        )
    }

    func testPersistenceFailureNeverReleasesReservedValue() {
        let store = MemorySecurityStateStore()
        store.failPersist = true

        XCTAssertThrowsError(try SecurityLifecycle(store: store).beginSession())
        XCTAssertEqual(store.state.sessionEpoch, 0)
        XCTAssertThrowsError(
            try SecurityLifecycle(store: store).reserveNonce(channel: 1, senderRole: 1, keyEpoch: 1)
        )
        XCTAssertTrue(store.state.nonceHighWatermarks.isEmpty)
        XCTAssertThrowsError(try SecurityLifecycle(store: store).consumeRotationNonceHash(Data(repeating: 1, count: 32)))
        XCTAssertTrue(store.state.usedRotationNonceHashes.isEmpty)
    }

    func testStoredSessionIdentityBindingFailsBeforeEpochReservation() throws {
        let service = "dev.vibescreen.session-identity-tests.\(UUID().uuidString)"
        let identityStore = KeychainDeviceIdentityStore(service: service)
        let original = try identityStore.createIfMissing(deviceID: "mac-host")
        let pairingIdentifier = String(repeating: "a", count: 64)
        let names = try PairedDeviceSecretNames(
            sharedSecret: "pairing.\(pairingIdentifier).shared.v1",
            bootstrapSecret: "pairing.\(pairingIdentifier).bootstrap.v1",
            identityBinding: PairedHostIdentityBinding.keychainName(
                pairingIdentifier: pairingIdentifier
            ),
            pairingIdentifier: pairingIdentifier
        )
        let secrets = MemoryInternetPairingSecretStore()
        try secrets.persist(name: names.sharedSecret, secret: Data(repeating: 0x21, count: 32))
        try secrets.persist(name: names.bootstrapSecret, secret: Data(repeating: 0x22, count: 32))
        try secrets.persist(
            name: try XCTUnwrap(names.identityBinding),
            secret: PairedHostIdentityBinding.encode(original.publicIdentity)
        )
        let stateStore = MemorySecurityStateStore()
        stateStore.state.sessionEpoch = 10
        let security = PlatformSessionSecurity(
            deviceID: "mac-host",
            peerID: "tablet|key:test",
            identityStore: identityStore,
            stateStore: stateStore
        )

        let valid = try security.startStoredProtectedInternetSession(
            sessionIdentifier: "identity-binding-valid",
            localRole: .host,
            identityEpoch: 1,
            secretNames: names,
            transcriptContext: Data(repeating: 0x23, count: 32),
            agreedSessionEpoch: 11,
            secretStore: secrets
        )
        XCTAssertEqual(valid.identity.publicIdentity, original.publicIdentity)
        XCTAssertEqual(stateStore.state.sessionEpoch, 11)
        valid.packetCipher.close()

        try identityStore.delete(deviceID: "mac-host", keyEpoch: 1)
        XCTAssertThrowsError(try security.startStoredProtectedInternetSession(
            sessionIdentifier: "identity-binding-missing-alias",
            localRole: .host,
            identityEpoch: 1,
            secretNames: names,
            transcriptContext: Data(repeating: 0x24, count: 32),
            agreedSessionEpoch: 12,
            secretStore: secrets
        ))
        XCTAssertEqual(stateStore.state.sessionEpoch, 11)

        let replacement = try identityStore.createIfMissing(deviceID: "mac-host")
        XCTAssertNotEqual(replacement.publicIdentity.keyID, original.publicIdentity.keyID)
        XCTAssertThrowsError(try security.startStoredProtectedInternetSession(
            sessionIdentifier: "identity-binding-mismatch",
            localRole: .host,
            identityEpoch: 1,
            secretNames: names,
            transcriptContext: Data(repeating: 0x25, count: 32),
            agreedSessionEpoch: 12,
            secretStore: secrets
        ))
        XCTAssertEqual(stateStore.state.sessionEpoch, 11)

        try secrets.delete(name: try XCTUnwrap(names.identityBinding))
        XCTAssertThrowsError(try security.startStoredProtectedInternetSession(
            sessionIdentifier: "identity-binding-legacy",
            localRole: .host,
            identityEpoch: 1,
            secretNames: names,
            transcriptContext: Data(repeating: 0x26, count: 32),
            agreedSessionEpoch: 12,
            secretStore: secrets
        )) { error in
            XCTAssertTrue(error.localizedDescription.contains("credentials were retained"))
        }
        XCTAssertEqual(stateStore.state.sessionEpoch, 11)
        XCTAssertNotNil(try secrets.load(name: names.sharedSecret))
        XCTAssertNotNil(try secrets.load(name: names.bootstrapSecret))

        try identityStore.delete(deviceID: "mac-host", keyEpoch: 1)
    }

    func testRotationNonceTombstoneMatchesGoAndSurvivesRestart() throws {
        let identity = PlatformPublicIdentity(
            deviceID: "host",
            keyID: String(repeating: "a", count: 64),
            keyEpoch: 1,
            signingPublicKey: Data([UInt8(0x04)] + (0..<64).map(UInt8.init))
        )
        let hash = try identity.rotationNonceHash(nonce: Data((0..<16).map(UInt8.init)))
        XCTAssertEqual(hash.hex, "d5f91aab0a4c23c4c710b25146f2350906ea19fac62c79dda0f61fda6f4308c9")

        let store = MemorySecurityStateStore()
        try SecurityLifecycle(store: store).consumeRotationNonceHash(hash)
        XCTAssertThrowsError(try SecurityLifecycle(store: store).consumeRotationNonceHash(hash))
        XCTAssertEqual(store.state.usedRotationNonceHashes, [hash.hex])
    }

    func testInitialDerivationMatchesCrossPlatformFixedVector() throws {
        let keys = try TrafficKeyDerivation.initial(
            sharedSecret: Data((1...32).map(UInt8.init)),
            bootstrapSecret: Data((32...63).map(UInt8.init)),
            context: Data(hex: "d6f7dfe489e792765bcabd79578ec8d1eb95891a459a8414dfcf668a592dd670")
        )

        XCTAssertEqual(keys.keyID, "d249fc90df874566874890c85690ec42cdb979fa1cf7601ce112f7f261b88eda")
        XCTAssertEqual(
            (keys.hostControl + keys.deviceControl + keys.hostMedia + keys.deviceMedia).hex,
            "2813943a29749dde00d152db6822da75c742819cc0ada7d0f71c597123531c70" +
                "88f8b6f39161e266db1b899871e7505a3675f9a7c5c88c213b91042ebd3a1244" +
                "cf62a7f3926e10308e0402d5e51397afc1c6d666dd2dc6a856bf2ebd0106307f3" +
                "f014c1e536fdd26670c84a0737526b2fc6052ca0b08be2e5d5197fc126e4c46"
        )
    }

    func testRotationRequiresNextEpochAndSeparatesKeys() throws {
        let current = try TrafficKeyDerivation.initial(
            sharedSecret: Data((1...32).map(UInt8.init)),
            bootstrapSecret: Data((32...63).map(UInt8.init)),
            context: Data(repeating: 7, count: 32)
        )
        let rotated = try TrafficKeyDerivation.rotate(
            current: current,
            nextEpoch: 2,
            updateNonce: Data((64...79).map(UInt8.init))
        )

        XCTAssertEqual(rotated.keyEpoch, 2)
        XCTAssertNotEqual(rotated.keyID, current.keyID)
        XCTAssertEqual(Set([rotated.hostControl, rotated.deviceControl, rotated.hostMedia, rotated.deviceMedia]).count, 4)
        XCTAssertThrowsError(try TrafficKeyDerivation.rotate(current: current, nextEpoch: 3, updateNonce: Data((64...79).map(UInt8.init))))
    }

    func testTrafficPacketAESGCMAuthenticatesHeader() throws {
        let key = Data(repeating: 0, count: 32)
        let nonce = Data(repeating: 0, count: 12)
        let header = Data("header".utf8)
        let knownCiphertext = try TrafficPacketCryptography.seal(
            plaintext: Data(), key: key, nonce: nonce, authenticatedHeader: Data()
        )
        XCTAssertEqual(knownCiphertext.hex, "530f8afbc74536b9a963b4f1c4cb738b")
        let ciphertext = try TrafficPacketCryptography.seal(
            plaintext: Data(), key: key, nonce: nonce, authenticatedHeader: header
        )
        XCTAssertEqual(
            try TrafficPacketCryptography.open(
                ciphertextAndTag: ciphertext, key: key, nonce: nonce, authenticatedHeader: header
            ),
            Data()
        )
        XCTAssertThrowsError(
            try TrafficPacketCryptography.open(
                ciphertextAndTag: ciphertext, key: key, nonce: nonce, authenticatedHeader: Data("tampered".utf8)
            )
        )
    }

    func testOldCipherFailsClosedForSealAndOpenAfterDurableEpochAdvance() throws {
        let store = MemorySecurityStateStore()
        let lifecycle = SecurityLifecycle(store: store)
        XCTAssertEqual(try lifecycle.reserveSessionEpoch(1), 1)
        let pair = try PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "epoch-bound-session",
            sharedSecret: Data(repeating: 0x31, count: 32),
            bootstrapSecret: Data(repeating: 0x32, count: 32),
            transcriptContext: Data(repeating: 0x33, count: 32),
            sessionEpoch: 1,
            requireActiveEpoch: lifecycle.requireCurrentSessionEpoch
        )
        let oldRecord = try pair.device.seal(Data("old".utf8), channel: .control)
        XCTAssertEqual(pair.host.open(oldRecord, channel: .control), Data("old".utf8))

        XCTAssertEqual(try lifecycle.reserveSessionEpoch(2), 2)
        let queue = DispatchQueue(label: "stale-cipher-race", attributes: .concurrent)
        let group = DispatchGroup()
        let lock = NSLock()
        var sealFailures = 0
        var openFailures = 0
        for _ in 0..<32 {
            group.enter()
            queue.async {
                defer { group.leave() }
                do {
                    _ = try pair.device.seal(Data("stale".utf8), channel: .control)
                } catch {
                    lock.lock(); sealFailures += 1; lock.unlock()
                }
                if pair.host.open(oldRecord, channel: .control) == nil {
                    lock.lock(); openFailures += 1; lock.unlock()
                }
            }
        }
        XCTAssertEqual(group.wait(timeout: .now() + 2), .success)
        XCTAssertEqual(sealFailures, 32)
        XCTAssertEqual(openFailures, 32)

        let currentPair = try PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "epoch-bound-session-2",
            sharedSecret: Data(repeating: 0x31, count: 32),
            bootstrapSecret: Data(repeating: 0x32, count: 32),
            transcriptContext: Data(repeating: 0x34, count: 32),
            sessionEpoch: 2,
            requireActiveEpoch: lifecycle.requireCurrentSessionEpoch
        )
        let currentRecord = try currentPair.device.seal(Data("current".utf8), channel: .control)
        XCTAssertEqual(currentPair.host.open(currentRecord, channel: .control), Data("current".utf8))
    }

    func testOpenAndConcurrentEpochAdvanceAreSerializedByDurableEpochLock() throws {
        let store = MemorySecurityStateStore()
        let lifecycle = SecurityLifecycle(store: store)
        XCTAssertEqual(try lifecycle.reserveSessionEpoch(1), 1)
        let material = (
            shared: Data(repeating: 0x51, count: 32),
            bootstrap: Data(repeating: 0x52, count: 32),
            context: Data(repeating: 0x53, count: 32)
        )
        let recordPair = try PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "epoch-open-interleaving",
            sharedSecret: material.shared,
            bootstrapSecret: material.bootstrap,
            transcriptContext: material.context,
            sessionEpoch: 1,
            requireActiveEpoch: lifecycle.requireCurrentSessionEpoch
        )
        let record = try recordPair.device.seal(Data("epoch-one".utf8), channel: .control)
        let openEntered = DispatchSemaphore(value: 0)
        let releaseOpen = DispatchSemaphore(value: 0)
        let openFinished = DispatchSemaphore(value: 0)
        let reserveStarted = DispatchSemaphore(value: 0)
        let reserveFinished = DispatchSemaphore(value: 0)
        let opened = LockedOptionalData()
        let reservation = LockedEpochReservation()
        let interleavedPair = try PlatformSessionPacketCipher.selfTestPair(
            sessionIdentifier: "epoch-open-interleaving",
            sharedSecret: material.shared,
            bootstrapSecret: material.bootstrap,
            transcriptContext: material.context,
            sessionEpoch: 1,
            withActiveEpoch: { epoch, operation in
                try lifecycle.withActiveSessionEpoch(epoch) {
                    openEntered.signal()
                    guard releaseOpen.wait(timeout: .now() + 2) == .success else {
                        throw PlatformSecurityError.persistenceFailure("test latch timed out")
                    }
                    return try operation()
                }
            }
        )

        DispatchQueue.global().async {
            opened.set(interleavedPair.host.open(record, channel: .control))
            openFinished.signal()
        }
        XCTAssertEqual(openEntered.wait(timeout: .now() + 2), .success)
        DispatchQueue.global().async {
            reserveStarted.signal()
            do {
                reservation.succeed(try lifecycle.reserveSessionEpoch(2))
            } catch {
                reservation.fail(error)
            }
            reserveFinished.signal()
        }
        XCTAssertEqual(reserveStarted.wait(timeout: .now() + 2), .success)
        XCTAssertEqual(
            reserveFinished.wait(timeout: .now() + 0.05),
            .timedOut,
            "N+1 reservation must wait while the N open transaction owns the durable epoch lock."
        )
        releaseOpen.signal()
        XCTAssertEqual(openFinished.wait(timeout: .now() + 2), .success)
        XCTAssertEqual(opened.value, Data("epoch-one".utf8))
        XCTAssertEqual(reserveFinished.wait(timeout: .now() + 2), .success)
        XCTAssertEqual(reservation.value, 2)
        XCTAssertNil(reservation.errorDescription)
        XCTAssertEqual(store.state.sessionEpoch, 2)
        XCTAssertNil(interleavedPair.host.open(record, channel: .control))
    }
}

private func signedTombstone(
    authorityKey: TestSigningKey,
    authority: PlatformPublicIdentity,
    peer: PlatformPublicIdentity,
    sequence: UInt64
) throws -> PairedDeviceRevocationTombstone {
    let unsigned = PairedDeviceRevocationTombstone(
        peerIdentity: peer,
        sequence: sequence,
        revokedAtUnixSeconds: 1_800_000_000,
        nonce: Data((0..<16).map(UInt8.init)),
        reasonCode: "user_requested",
        authority: authority,
        authoritySignature: Data()
    )
    return PairedDeviceRevocationTombstone(
        peerIdentity: peer,
        sequence: sequence,
        revokedAtUnixSeconds: unsigned.revokedAtUnixSeconds,
        nonce: unsigned.nonce,
        reasonCode: unsigned.reasonCode,
        authority: authority,
        authoritySignature: try authorityKey.sign(unsigned.signingDigest())
    )
}

private final class TestSigningKey {
    let identity: PlatformPublicIdentity
    private let privateKey: SecKey

    init(deviceID: String, keyEpoch: UInt64) throws {
        var creationError: Unmanaged<CFError>?
        guard let privateKey = SecKeyCreateRandomKey([
            kSecAttrKeyType as String: kSecAttrKeyTypeECSECPrimeRandom,
            kSecAttrKeySizeInBits as String: 256
        ] as CFDictionary, &creationError),
        let publicKey = SecKeyCopyPublicKey(privateKey) else {
            throw creationError?.takeRetainedValue()
                ?? PlatformSecurityError.persistenceFailure("Unable to create test signing key.")
        }
        var exportError: Unmanaged<CFError>?
        guard let encoded = SecKeyCopyExternalRepresentation(publicKey, &exportError) as Data? else {
            throw exportError?.takeRetainedValue()
                ?? PlatformSecurityError.persistenceFailure("Unable to export test signing key.")
        }
        self.privateKey = privateKey
        self.identity = PlatformPublicIdentity(
            deviceID: deviceID,
            keyID: SHA256.hash(data: encoded).map { String(format: "%02x", $0) }.joined(),
            keyEpoch: keyEpoch,
            signingPublicKey: encoded
        )
    }

    func sign(_ digest: Data) throws -> Data {
        var signingError: Unmanaged<CFError>?
        guard let signature = SecKeyCreateSignature(
            privateKey,
            .ecdsaSignatureDigestX962SHA256,
            digest as CFData,
            &signingError
        ) as Data? else {
            throw signingError?.takeRetainedValue()
                ?? PlatformSecurityError.persistenceFailure("Unable to sign test revocation.")
        }
        return signature
    }
}

private final class MemorySecurityStateStore: SecurityStateStore {
    var state = PersistedSecurityState()
    var failPersist = false
    var failPersistCalls: Set<Int> = []
    private var persistCallCount = 0
    func load() throws -> PersistedSecurityState { state }
    func persist(_ state: PersistedSecurityState) throws {
        persistCallCount += 1
        if failPersist || failPersistCalls.contains(persistCallCount) {
            throw PlatformSecurityError.persistenceFailure("injected")
        }
        self.state = state
    }
}

private final class PairingValidationFailureStore: SecurityStateStore {
    private(set) var validationCalls = 0

    func load() throws -> PersistedSecurityState {
        XCTFail("Pairing validation must not fall back to an unbound state load.")
        return PersistedSecurityState()
    }

    func persist(_ state: PersistedSecurityState) throws {
        XCTFail("Pairing validation failure must not persist state.")
    }

    func validatePairingBinding(
        pairingIdentifier _: String
    ) throws -> PersistedSecurityState {
        validationCalls += 1
        throw PlatformSecurityError.persistenceFailure("injected missing durable state")
    }
}

private final class CountingInternetPairingSecretStore: InternetPairingSecretStore {
    private(set) var loadCalls = 0

    func load(name _: String) throws -> Data? {
        loadCalls += 1
        return nil
    }

    func persist(name _: String, secret _: Data) throws {}
    func delete(name _: String) throws {}
}

private final class KeychainPairingStateFixture {
    let service = "dev.vibescreen.pairing-state-tests.\(UUID().uuidString)"
    let peerID = "tablet|key:\(UUID().uuidString)"
    let pairingIdentifier = String(repeating: "a", count: 64)
    lazy var store = KeychainSecurityStateStore(
        peerID: peerID,
        service: service,
        legacyAccount: nil,
        legacyCleanupAccount: nil
    )
    lazy var rawStore = KeychainSecretStore(service: service)

    func cleanup() {
        try? rawStore.delete(name: store.account)
        if let bindingAccount = store.bindingAccount {
            try? rawStore.delete(name: bindingAccount)
        }
    }
}

private final class LockedOptionalData: @unchecked Sendable {
    private let lock = NSLock()
    private var stored: Data?

    var value: Data? {
        lock.lock()
        defer { lock.unlock() }
        return stored
    }

    func set(_ value: Data?) {
        lock.lock()
        stored = value
        lock.unlock()
    }
}

private final class LockedEpochReservation: @unchecked Sendable {
    private let lock = NSLock()
    private var storedValue: UInt64?
    private var storedErrorDescription: String?

    var value: UInt64? {
        lock.lock()
        defer { lock.unlock() }
        return storedValue
    }

    var errorDescription: String? {
        lock.lock()
        defer { lock.unlock() }
        return storedErrorDescription
    }

    func succeed(_ value: UInt64) {
        lock.lock()
        storedValue = value
        lock.unlock()
    }

    func fail(_ error: Error) {
        lock.lock()
        storedErrorDescription = error.localizedDescription
        lock.unlock()
    }
}

private final class MemoryPairedDeviceSecretStore: PairedDeviceSecretStore {
    private(set) var deletedNames: [String] = []
    private(set) var attemptedNames: [String] = []
    var failingNames: Set<String>

    var failingName: String? {
        get { failingNames.first }
        set { failingNames = newValue.map { Set([$0]) } ?? [] }
    }

    init(failingName: String? = nil, failingNames: Set<String> = []) {
        self.failingNames = failingName.map { Set([$0]) } ?? failingNames
    }

    func delete(name: String) throws {
        attemptedNames.append(name)
        if failingNames.contains(name) {
            throw PlatformSecurityError.persistenceFailure("injected secret deletion failure")
        }
        deletedNames.append(name)
    }
}

private final class MemoryInternetPairingSecretStore: InternetPairingSecretStore {
    private var values: [String: Data] = [:]

    func load(name: String) throws -> Data? { values[name] }
    func persist(name: String, secret: Data) throws { values[name] = secret }
    func delete(name: String) throws { values.removeValue(forKey: name) }
}

private extension Data {
    init(hex: String) {
        self.init(stride(from: 0, to: hex.count, by: 2).map { index in
            let start = hex.index(hex.startIndex, offsetBy: index)
            let end = hex.index(start, offsetBy: 2)
            return UInt8(hex[start..<end], radix: 16)!
        })
    }

    var hex: String { map { String(format: "%02x", $0) }.joined() }
}
