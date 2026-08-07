package dev.telemachus.display.internet.security

import android.content.Context
import dev.telemachus.display.internet.AndroidWebRtcPeerEngine
import dev.telemachus.display.internet.IceServer
import dev.telemachus.display.internet.IceTransportPolicy
import dev.telemachus.display.internet.InternetProductAdmissionGate
import dev.telemachus.display.internet.PeerConfiguration
import dev.telemachus.display.internet.PeerRole
import dev.telemachus.display.internet.SignalingConfiguration
import dev.telemachus.display.internet.VideoProfile
import java.nio.ByteBuffer
import java.security.MessageDigest

/** Production composition returned only after paired secrets are loaded from encrypted storage. */
class AndroidStoredInternetSession internal constructor(
    val identity: AndroidDeviceIdentity,
    val engine: AndroidWebRtcPeerEngine,
    val configuration: PeerConfiguration,
) : AutoCloseable {
    override fun close() {
        try {
            engine.close()
        } finally {
            configuration.signaling?.close()
            configuration.iceServers.forEach(IceServer::close)
        }
    }
}

/**
 * Fail-closed bridge from AndroidKeyStore-backed pairing state to the production WebRTC adapter.
 * Pairing secrets are persisted as one AES-GCM record so a crash cannot expose a half-written pair.
 */
class AndroidStoredInternetSessionFactory private constructor(
    val localDeviceId: String,
    private val sessionSecurity: AndroidSessionSecurity,
    private val loadSecret: (String) -> ByteArray?,
    private val persistSecret: (String, ByteArray) -> Unit,
    private val deleteSecret: (String) -> Unit,
    private val engineFactory: ((VideoProfile) -> Unit) -> AndroidWebRtcPeerEngine,
) {
    constructor(
        context: Context,
        localDeviceId: String,
        secretStore: AndroidSecretStore = AndroidSecretStore(context.applicationContext),
        sessionSecurity: AndroidSessionSecurity =
            AndroidSessionSecurity(localDeviceId, context.applicationContext),
    ) : this(
        localDeviceId = localDeviceId,
        sessionSecurity = sessionSecurity,
        loadSecret = secretStore::load,
        persistSecret = secretStore::persist,
        deleteSecret = secretStore::delete,
        engineFactory = { videoProfileSink -> AndroidWebRtcPeerEngine(context.applicationContext, videoProfileSink) },
    )

    internal constructor(
        localDeviceId: String,
        sessionSecurity: AndroidSessionSecurity,
        loadSecret: (String) -> ByteArray?,
        persistSecret: (String, ByteArray) -> Unit,
        deleteSecret: (String) -> Unit,
    ) : this(
        localDeviceId = localDeviceId,
        sessionSecurity = sessionSecurity,
        loadSecret = loadSecret,
        persistSecret = persistSecret,
        deleteSecret = deleteSecret,
        engineFactory = { error("Android WebRTC engine is unavailable in this test seam") },
    )

    private val pairingPersistence =
        PairingPersistenceTransaction(
            object : PairingPersistenceSlots {
                override fun load(name: String): ByteArray? = loadSecret(name)
                override fun persist(name: String, value: ByteArray) = persistSecret(name, value)
                override fun delete(name: String) = deleteSecret(name)
            },
            PAIRING_CLEANUP_MARKER_NAME,
        )

    init {
        require(localDeviceId.isNotBlank()) { "Device ID must not be blank" }
    }

    fun persistPairingSecrets(
        pairingIdentifier: String,
        sharedSecret: ByteArray,
        bootstrapSecret: ByteArray,
    ) {
        InternetProductAdmissionGate.requireHeld()
        require(pairingIdentifier.isNotBlank()) { "Pairing identifier must not be blank" }
        require(sharedSecret.isNotEmpty()) { "Shared secret must not be empty" }
        require(bootstrapSecret.size == BOOTSTRAP_SECRET_BYTES) { "Bootstrap secret must contain 32 bytes" }
        val record = PairingSecretRecordCodec.encode(sharedSecret, bootstrapSecret)
        try {
            pairingPersistence.begin(secretName(pairingIdentifier), record, pairingIdentifier)
        } finally {
            record.fill(0)
        }
    }

    fun completePairingPersistence(
        pairingIdentifier: String,
        commitBusinessState: () -> Unit,
        cleanupBusinessState: () -> Unit,
    ) {
        InternetProductAdmissionGate.requireHeld()
        require(pairingIdentifier.isNotBlank()) { "Pairing identifier must not be blank" }
        pairingPersistence.complete(
            secretName(pairingIdentifier),
            commitBusinessState,
            cleanupBusinessState,
        )
    }

    fun retryPendingPairingPersistenceCleanup(
        currentPairingIdentifier: String? = null,
        cleanupBusinessState: (String) -> Unit = {},
    ): Boolean {
        InternetProductAdmissionGate.requireHeld()
        return pairingPersistence.retryPendingCleanup { targetName, storedPairingIdentifier ->
            val pairingIdentifier =
                storedPairingIdentifier
                    ?: currentPairingIdentifier?.takeIf { secretName(it) == targetName }
            if (pairingIdentifier != null) cleanupBusinessState(pairingIdentifier)
        }
    }

    fun hasPendingPairingPersistenceCleanup(): Boolean {
        InternetProductAdmissionGate.requireHeld()
        return pairingPersistence.hasPendingCleanup()
    }

    fun removePairingSecrets(pairingIdentifier: String) {
        require(pairingIdentifier.isNotBlank()) { "Pairing identifier must not be blank" }
        deleteSecret(secretName(pairingIdentifier))
    }

    fun reserveNextIdentityEpoch(): Long = sessionSecurity.reserveNextIdentityEpoch()

    fun authorizeIdentity(identity: InternetPairingIdentity) = sessionSecurity.authorizeIdentity(identity)

    fun <T> withFreshSessionEpochCandidate(
        pairingIdentifier: String,
        identity: InternetPairingIdentity,
        sessionEpoch: Long,
        block: () -> T,
    ): T =
        sessionSecurity.withFreshSessionEpochCandidate(
            pairingIdentifier,
            identity,
            sessionEpoch,
            block,
        )

    fun create(
        pairingIdentifier: String,
        sessionId: String,
        localRole: PeerRole,
        expectedIdentity: InternetPairingIdentity,
        authoritativeSessionEpoch: Long,
        transcriptContext: ByteArray,
        iceServers: List<IceServer>,
        signaling: SignalingConfiguration,
        iceTransportPolicy: IceTransportPolicy = IceTransportPolicy.ALL,
        videoProfileSink: (VideoProfile) -> Unit = {},
    ): AndroidStoredInternetSession {
        require(pairingIdentifier.isNotBlank()) { "Pairing identifier must not be blank" }
        require(sessionId.isNotBlank()) { "Session ID must not be blank" }
        require(signaling.role == localRole) { "Signaling role must match the local session role" }
        require(transcriptContext.size == TRANSCRIPT_CONTEXT_BYTES) { "Transcript context must contain 32 bytes" }
        val stored =
            checkNotNull(loadSecret(secretName(pairingIdentifier))) {
                "Paired-device session secrets are missing from encrypted Android storage"
            }
        val decoded =
            try {
                PairingSecretRecordCodec.decode(stored)
            } finally {
                stored.fill(0)
            }
        try {
            val active =
                sessionSecurity.startSession(
                    pairingIdentifier = pairingIdentifier,
                    expectedIdentity = expectedIdentity,
                    authoritativeSessionEpoch = authoritativeSessionEpoch,
                    sharedSecret = decoded.sharedSecret,
                    bootstrapSecret = decoded.bootstrapSecret,
                    transcriptContext = transcriptContext,
                )
            var cipher: AndroidSessionPacketCipher? = null
            try {
                cipher =
                    AndroidSessionPacketCipher(
                        sessionId = sessionId,
                        sessionEpoch = active.sessionEpoch,
                        pairingIdentifier = pairingIdentifier,
                        identityEpoch = expectedIdentity.keyEpoch,
                        localRole = localRole,
                        platformSecurity = sessionSecurity,
                        initialKeys = active.trafficKeys,
                    )
                check(active.sessionEpoch == authoritativeSessionEpoch) {
                    "Platform security returned a session epoch that does not match the authority reservation"
                }
                val configuration =
                    PeerConfiguration(
                        iceServers = iceServers,
                        sessionId = sessionId,
                        sessionEpoch = active.sessionEpoch,
                        signaling = signaling,
                        sessionCipher = cipher,
                        iceTransportPolicy = iceTransportPolicy,
                    )
                return AndroidStoredInternetSession(
                    identity = active.identity,
                    engine = engineFactory(videoProfileSink),
                    configuration = configuration,
                )
            } catch (failure: Throwable) {
                try {
                    cipher?.close() ?: active.trafficKeys.close()
                } catch (cleanupFailure: Throwable) {
                    failure.addSuppressed(cleanupFailure)
                }
                throw failure
            }
        } finally {
            decoded.close()
        }
    }

    private fun secretName(pairingIdentifier: String): String =
        "$PAIRING_SECRET_PREFIX.${MessageDigest.getInstance("SHA-256").digest(pairingIdentifier.toByteArray()).toHex()}"

    private fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it) }

    companion object {
        private const val PAIRING_SECRET_PREFIX = "phase3.pairing.v1"
        private const val PAIRING_CLEANUP_MARKER_NAME = "phase3.pairing.persistence-cleanup.v1"
        private const val BOOTSTRAP_SECRET_BYTES = 32
        private const val TRANSCRIPT_CONTEXT_BYTES = 32
    }
}

internal data class PairingSecretRecord(
    val sharedSecret: ByteArray,
    val bootstrapSecret: ByteArray,
) : AutoCloseable {
    override fun close() {
        sharedSecret.fill(0)
        bootstrapSecret.fill(0)
    }
}

internal object PairingSecretRecordCodec {
    private const val VERSION: Byte = 1
    private const val HEADER_BYTES = 1 + Int.SIZE_BYTES
    private const val BOOTSTRAP_SECRET_BYTES = 32
    private const val MAX_SHARED_SECRET_BYTES = 4 * 1024

    fun encode(
        sharedSecret: ByteArray,
        bootstrapSecret: ByteArray,
    ): ByteArray {
        require(sharedSecret.isNotEmpty() && sharedSecret.size <= MAX_SHARED_SECRET_BYTES) {
            "Shared secret size is outside the supported range"
        }
        require(bootstrapSecret.size == BOOTSTRAP_SECRET_BYTES) { "Bootstrap secret must contain 32 bytes" }
        return ByteBuffer
            .allocate(HEADER_BYTES + sharedSecret.size + bootstrapSecret.size)
            .put(VERSION)
            .putInt(sharedSecret.size)
            .put(sharedSecret)
            .put(bootstrapSecret)
            .array()
    }

    fun decode(record: ByteArray): PairingSecretRecord {
        require(record.size >= HEADER_BYTES + 1 + BOOTSTRAP_SECRET_BYTES) { "Stored pairing secret record is truncated" }
        val buffer = ByteBuffer.wrap(record)
        require(buffer.get() == VERSION) { "Stored pairing secret record version is unsupported" }
        val sharedLength = buffer.int
        require(sharedLength in 1..MAX_SHARED_SECRET_BYTES) { "Stored shared secret length is invalid" }
        require(buffer.remaining() == sharedLength + BOOTSTRAP_SECRET_BYTES) { "Stored pairing secret record length is invalid" }
        val shared = ByteArray(sharedLength).also(buffer::get)
        val bootstrap = ByteArray(BOOTSTRAP_SECRET_BYTES).also(buffer::get)
        return PairingSecretRecord(shared, bootstrap)
    }
}
