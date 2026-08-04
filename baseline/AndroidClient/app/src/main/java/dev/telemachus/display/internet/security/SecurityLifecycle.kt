package dev.telemachus.display.internet.security

import android.content.Context
import android.content.SharedPreferences
import java.nio.ByteBuffer

data class DurableSecurityState(
    val sessionEpoch: Long = 0,
    val revocationSequence: Long = 0,
    val revoked: Boolean = false,
    val nonceHighWatermarks: Map<String, Long> = emptyMap(),
    val usedRotationNonceHashes: Set<String> = emptySet(),
)

interface SecurityStateStore {
    fun load(): DurableSecurityState

    /** Must durably commit the complete state before returning. */
    fun persist(state: DurableSecurityState)
}

class SecurityLifecycle(
    private val store: SecurityStateStore,
) {
    /** Persists the peer-authorized epoch before traffic keys or nonces can use it. */
    fun reserveSessionEpoch(authoritativeEpoch: Long): Long =
        synchronized(persistenceLock) {
            val current = store.load()
            check(!current.revoked) { "The local device identity has been revoked" }
            require(authoritativeEpoch > current.sessionEpoch) {
                "Authoritative session epoch must exceed the durable high-water mark"
            }
            store.persist(current.copy(sessionEpoch = authoritativeEpoch))
            authoritativeEpoch
        }

    fun reserveNonce(
        channel: Int,
        senderRole: Int,
        keyEpoch: Long,
    ): ByteArray =
        synchronized(persistenceLock) {
            require(channel > 0 && senderRole > 0 && keyEpoch > 0) {
                "Channel, sender role, and key epoch must be positive"
            }
            val current = store.load()
            check(!current.revoked) { "The local device identity has been revoked" }
            val counterKey = "$channel:$senderRole:$keyEpoch"
            val previous = current.nonceHighWatermarks[counterKey] ?: 0
            check(previous < Long.MAX_VALUE) { "Nonce sequence exhausted; rotate traffic keys" }
            val sequence = previous + 1
            store.persist(
                current.copy(nonceHighWatermarks = current.nonceHighWatermarks + (counterKey to sequence)),
            )
            ByteBuffer.allocate(NONCE_BYTES).putInt(channel).putLong(sequence).array()
        }

    fun applyRevocation(sequence: Long) {
        synchronized(persistenceLock) {
            val current = store.load()
            require(sequence > current.revocationSequence) { "Revocation sequence must increase" }
            store.persist(current.copy(revocationSequence = sequence, revoked = true))
        }
    }

    /** Persists the tombstone before a key rotation is acknowledged. */
    fun consumeRotationNonceHash(nonceHash: ByteArray) {
        require(nonceHash.size == SHA256_BYTES) { "Rotation nonce hashes must be SHA-256 values" }
        synchronized(persistenceLock) {
            val current = store.load()
            check(!current.revoked) { "The local device identity has been revoked" }
            val encoded = nonceHash.toHex()
            require(encoded !in current.usedRotationNonceHashes) { "Rotation nonce was already used" }
            store.persist(current.copy(usedRotationNonceHashes = current.usedRotationNonceHashes + encoded))
        }
    }

    private companion object {
        const val NONCE_BYTES = 12
        const val SHA256_BYTES = 32
        val persistenceLock = Any()
    }
}

/** SharedPreferences contains counters and revocation status only, never keys. */
class SharedPreferencesSecurityStateStore(
    context: Context,
) : SecurityStateStore {
    private val preferences: SharedPreferences =
        context.getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)

    override fun load(): DurableSecurityState {
        val counters =
            preferences.all
                .filterKeys { it.startsWith(NONCE_PREFIX) }
                .mapNotNull { (key, value) ->
                    (value as? Long)?.let { key.removePrefix(NONCE_PREFIX) to it }
                }.toMap()
        val state = DurableSecurityState(
            sessionEpoch = preferences.getLong(SESSION_EPOCH, 0),
            revocationSequence = preferences.getLong(REVOCATION_SEQUENCE, 0),
            revoked = preferences.getBoolean(REVOKED, false),
            nonceHighWatermarks = counters,
            usedRotationNonceHashes = preferences.getStringSet(ROTATION_NONCE_HASHES, emptySet())?.toSet() ?: emptySet(),
        )
        check(state.sessionEpoch >= 0 && state.revocationSequence >= 0 && counters.values.all { it >= 0 }) {
            "Stored monotonic security state is invalid"
        }
        check(state.usedRotationNonceHashes.all { hash ->
            hash.length == 64 && hash.all { it in '0'..'9' || it in 'a'..'f' }
        }) {
            "Stored rotation nonce state is invalid"
        }
        return state
    }

    override fun persist(state: DurableSecurityState) {
        val editor =
            preferences
                .edit()
                .putLong(SESSION_EPOCH, state.sessionEpoch)
                .putLong(REVOCATION_SEQUENCE, state.revocationSequence)
                .putBoolean(REVOKED, state.revoked)
                .putStringSet(ROTATION_NONCE_HASHES, state.usedRotationNonceHashes)
        preferences.all.keys.filter { it.startsWith(NONCE_PREFIX) }.forEach(editor::remove)
        state.nonceHighWatermarks.forEach { (key, value) -> editor.putLong(NONCE_PREFIX + key, value) }
        check(editor.commit()) { "Failed to durably commit Phase 3 security state" }
    }

    companion object {
        const val PREFERENCES_NAME = "phase3_security_state"
        private const val SESSION_EPOCH = "session_epoch"
        private const val REVOCATION_SEQUENCE = "revocation_sequence"
        private const val REVOKED = "revoked"
        private const val ROTATION_NONCE_HASHES = "rotation_nonce_hashes"
        private const val NONCE_PREFIX = "nonce."
    }
}

private fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it) }
