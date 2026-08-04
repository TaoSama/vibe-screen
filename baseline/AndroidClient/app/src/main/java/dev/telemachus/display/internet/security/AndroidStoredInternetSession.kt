package dev.telemachus.display.internet.security

import android.content.Context
import dev.telemachus.display.internet.AndroidWebRtcPeerEngine
import dev.telemachus.display.internet.IceServer
import dev.telemachus.display.internet.IceTransportPolicy
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
        engine.close()
    }
}

/**
 * Fail-closed bridge from AndroidKeyStore-backed pairing state to the production WebRTC adapter.
 * Pairing secrets are persisted as one AES-GCM record so a crash cannot expose a half-written pair.
 */
class AndroidStoredInternetSessionFactory(
    context: Context,
    val localDeviceId: String,
    private val secretStore: AndroidSecretStore = AndroidSecretStore(context.applicationContext),
    private val sessionSecurity: AndroidSessionSecurity =
        AndroidSessionSecurity(localDeviceId, context.applicationContext),
) {
    private val applicationContext = context.applicationContext

    init {
        require(localDeviceId.isNotBlank()) { "Device ID must not be blank" }
    }

    fun persistPairingSecrets(
        pairingIdentifier: String,
        sharedSecret: ByteArray,
        bootstrapSecret: ByteArray,
    ) {
        require(pairingIdentifier.isNotBlank()) { "Pairing identifier must not be blank" }
        require(sharedSecret.isNotEmpty()) { "Shared secret must not be empty" }
        require(bootstrapSecret.size == BOOTSTRAP_SECRET_BYTES) { "Bootstrap secret must contain 32 bytes" }
        val record = PairingSecretRecordCodec.encode(sharedSecret, bootstrapSecret)
        try {
            secretStore.persist(secretName(pairingIdentifier), record)
        } finally {
            record.fill(0)
        }
    }

    fun removePairingSecrets(pairingIdentifier: String) {
        require(pairingIdentifier.isNotBlank()) { "Pairing identifier must not be blank" }
        secretStore.delete(secretName(pairingIdentifier))
    }

    fun reserveNextIdentityEpoch(): Long = sessionSecurity.reserveNextIdentityEpoch()

    fun authorizeIdentityEpoch(identityEpoch: Long) = sessionSecurity.authorizeIdentityEpoch(identityEpoch)

    fun <T> withFreshSessionEpochCandidate(sessionEpoch: Long, block: () -> T): T =
        sessionSecurity.withFreshSessionEpochCandidate(sessionEpoch, block)

    fun create(
        pairingIdentifier: String,
        sessionId: String,
        localRole: PeerRole,
        identityEpoch: Long,
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
            checkNotNull(secretStore.load(secretName(pairingIdentifier))) {
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
                    identityEpoch = identityEpoch,
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
                        localRole = localRole,
                        platformSecurity = sessionSecurity,
                        initialKeys = active.trafficKeys,
                    )
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
                    engine = AndroidWebRtcPeerEngine(applicationContext, videoProfileSink),
                    configuration = configuration,
                )
            } catch (failure: Throwable) {
                cipher?.close() ?: active.trafficKeys.close()
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
