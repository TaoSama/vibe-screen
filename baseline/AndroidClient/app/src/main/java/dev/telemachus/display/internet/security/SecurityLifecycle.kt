package dev.telemachus.display.internet.security

import android.content.Context
import android.content.SharedPreferences
import java.nio.ByteBuffer
import java.security.KeyStore
import java.security.MessageDigest

data class LegacySessionSecurityState(
    val sessionEpoch: Long,
    val nonceHighWatermarks: Map<String, Long>,
    val ownerIdentityEpoch: Long,
    val revocationSequence: Long,
    val revoked: Boolean,
)

data class DurableSecurityState(
    val sessionEpochHighWatermarks: Map<String, Long> = emptyMap(),
    val revocationSequenceHighWatermarks: Map<String, Long> = emptyMap(),
    val revoked: Boolean = false,
    val nonceHighWatermarks: Map<String, Long> = emptyMap(),
    val usedRotationNonceHashes: Set<String> = emptySet(),
    val identityEpochHighWatermark: Long = 0,
    val authorizedIdentityEpoch: Long = 0,
    val authorizedIdentityKeyId: String? = null,
    val legacySessionState: LegacySessionSecurityState? = null,
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
    fun reserveSessionEpoch(
        pairingScope: String,
        identityEpoch: Long,
        authoritativeEpoch: Long,
    ): Long =
        synchronized(persistenceLock) {
            val current = loadResolvedState(pairingScope, identityEpoch)
            check(!current.revoked) { "The local device identity has been revoked" }
            require(authoritativeEpoch < Long.MAX_VALUE) {
                "Authoritative session epoch is outside the supported range"
            }
            val previous = current.sessionEpochHighWatermarks[pairingScope] ?: 0
            require(authoritativeEpoch > previous) {
                "Authoritative session epoch must exceed the durable pairing high-water mark"
            }
            store.persist(
                current.copy(
                    sessionEpochHighWatermarks =
                        current.sessionEpochHighWatermarks + (pairingScope to authoritativeEpoch),
                ),
            )
            authoritativeEpoch
        }

    fun reserveNextIdentityEpoch(): Long =
        synchronized(persistenceLock) {
            val current = store.load()
            check(current.identityEpochHighWatermark < Long.MAX_VALUE - 1) { "Identity key epoch exhausted" }
            val next = current.identityEpochHighWatermark + 1
            store.persist(current.copy(identityEpochHighWatermark = next))
            next
        }

    fun authorizeIdentityEpoch(
        identityEpoch: Long,
        identityKeyId: String,
    ) {
        require(isSHA256Hex(identityKeyId)) { "Identity key ID must be a SHA-256 value" }
        synchronized(persistenceLock) {
            val current = store.load()
            require(identityEpoch in 1 until Long.MAX_VALUE && identityEpoch == current.identityEpochHighWatermark) {
                "Identity epoch was not durably reserved"
            }
            if (current.authorizedIdentityEpoch == identityEpoch && !current.revoked) {
                require(current.authorizedIdentityKeyId == identityKeyId) {
                    "Authorized identity key does not match the durable binding"
                }
                return
            }
            require(identityEpoch > current.authorizedIdentityEpoch) { "Identity epoch must advance" }
            store.persist(
                current.copy(
                    authorizedIdentityEpoch = identityEpoch,
                    authorizedIdentityKeyId = identityKeyId,
                    revoked = false,
                ),
            )
        }
    }

    fun requireAuthorizedIdentityKeyId(identityEpoch: Long): String =
        synchronized(persistenceLock) {
            val current = store.load()
            check(
                !current.revoked &&
                    current.authorizedIdentityEpoch == identityEpoch &&
                    current.authorizedIdentityKeyId != null,
            ) {
                "Identity epoch is not authorized"
            }
            check(isSHA256Hex(current.authorizedIdentityKeyId)) { "Authorized identity key binding is invalid" }
            current.authorizedIdentityKeyId
        }

    fun <T> withFreshSessionEpochCandidate(
        pairingScope: String,
        identityEpoch: Long,
        candidateEpoch: Long,
        block: () -> T,
    ): T =
        synchronized(persistenceLock) {
            val current = loadResolvedState(pairingScope, identityEpoch)
            check(!current.revoked) { "The local device identity has been revoked" }
            val previous = current.sessionEpochHighWatermarks[pairingScope] ?: 0
            require(candidateEpoch in 1 until Long.MAX_VALUE && candidateEpoch > previous) {
                "Internet lease session epoch must exceed the durable pairing high-water mark"
            }
            block()
        }

    fun <T> withActiveSessionEpoch(
        pairingScope: String,
        identityEpoch: Long,
        expectedEpoch: Long,
        block: () -> T,
    ): T =
        synchronized(persistenceLock) {
            val current = loadResolvedState(pairingScope, identityEpoch)
            check(
                !current.revoked &&
                    current.sessionEpochHighWatermarks[pairingScope] == expectedEpoch,
            ) { "Session epoch is no longer active" }
            block()
        }

    fun <T> withReservedSessionNonce(
        pairingScope: String,
        identityEpoch: Long,
        expectedSessionEpoch: Long,
        channel: Int,
        senderRole: Int,
        keyEpoch: Long,
        block: (ByteArray) -> T,
    ): T {
        require(expectedSessionEpoch > 0 && channel > 0 && senderRole > 0 && keyEpoch > 0) {
            "Session epoch, channel, sender role, and key epoch must be positive"
        }
        return synchronized(persistenceLock) {
            val current = loadResolvedState(pairingScope, identityEpoch)
            check(
                !current.revoked &&
                    current.sessionEpochHighWatermarks[pairingScope] == expectedSessionEpoch,
            ) { "Session epoch is no longer active" }
            val counterKey = scopedNonceCounterKey(pairingScope, channel, senderRole, keyEpoch)
            val previous = current.nonceHighWatermarks[counterKey] ?: 0
            check(previous < Long.MAX_VALUE) { "Nonce sequence exhausted; rotate traffic keys" }
            val sequence = previous + 1
            store.persist(
                current.copy(
                    nonceHighWatermarks = current.nonceHighWatermarks + (counterKey to sequence),
                ),
            )
            block(ByteBuffer.allocate(NONCE_BYTES).putInt(channel).putLong(sequence).array())
        }
    }

    fun reserveNonce(
        pairingScope: String,
        identityEpoch: Long,
        channel: Int,
        senderRole: Int,
        keyEpoch: Long,
    ): ByteArray =
        synchronized(persistenceLock) {
            require(channel > 0 && senderRole > 0 && keyEpoch > 0) {
                "Channel, sender role, and key epoch must be positive"
            }
            val current = loadResolvedState(pairingScope, identityEpoch)
            check(!current.revoked) { "The local device identity has been revoked" }
            val counterKey = scopedNonceCounterKey(pairingScope, channel, senderRole, keyEpoch)
            val previous = current.nonceHighWatermarks[counterKey] ?: 0
            check(previous < Long.MAX_VALUE) { "Nonce sequence exhausted; rotate traffic keys" }
            val sequence = previous + 1
            store.persist(
                current.copy(nonceHighWatermarks = current.nonceHighWatermarks + (counterKey to sequence)),
            )
            ByteBuffer.allocate(NONCE_BYTES).putInt(channel).putLong(sequence).array()
        }

    fun applyRevocation(
        pairingScope: String,
        identityEpoch: Long,
        sequence: Long,
    ) {
        synchronized(persistenceLock) {
            val current = loadResolvedState(pairingScope, identityEpoch)
            require(sequence < Long.MAX_VALUE) { "Revocation sequence is outside the supported range" }
            val previous = current.revocationSequenceHighWatermarks[pairingScope] ?: 0
            require(sequence > previous) { "Revocation sequence must increase within the pairing authority scope" }
            store.persist(
                current.copy(
                    revocationSequenceHighWatermarks =
                        current.revocationSequenceHighWatermarks + (pairingScope to sequence),
                    revoked = true,
                ),
            )
        }
    }

    /** Persists the tombstone before a key rotation is acknowledged. */
    fun consumeRotationNonceHash(
        identityEpoch: Long,
        nonceHash: ByteArray,
    ) {
        require(nonceHash.size == SHA256_BYTES) { "Rotation nonce hashes must be SHA-256 values" }
        synchronized(persistenceLock) {
            val current = store.load()
            check(!current.revoked && current.authorizedIdentityEpoch == identityEpoch) {
                "Identity epoch is not authorized"
            }
            val encoded = nonceHash.toHex()
            require(encoded !in current.usedRotationNonceHashes) { "Rotation nonce was already used" }
            store.persist(
                current.copy(usedRotationNonceHashes = current.usedRotationNonceHashes + encoded),
            )
        }
    }

    private fun loadResolvedState(
        pairingScope: String,
        identityEpoch: Long,
    ): DurableSecurityState {
        require(isScopeHash(pairingScope)) { "Pairing security scope is invalid" }
        val current = store.load()
        check(!current.revoked && current.authorizedIdentityEpoch == identityEpoch) {
            "Identity epoch is not authorized"
        }
        val legacy = current.legacySessionState ?: return current
        val resolved =
            when {
                identityEpoch == legacy.ownerIdentityEpoch -> {
                    check(pairingScope !in current.sessionEpochHighWatermarks) {
                        "Legacy session state collides with an existing pairing scope"
                    }
                    val scopedLegacyNonces =
                        legacy.nonceHighWatermarks.mapKeys { (key, _) -> "$pairingScope:$key" }
                    check(scopedLegacyNonces.keys.none { it in current.nonceHighWatermarks }) {
                        "Legacy nonce state collides with an existing pairing scope"
                    }
                    current.copy(
                        sessionEpochHighWatermarks =
                            if (legacy.sessionEpoch == 0L) {
                                current.sessionEpochHighWatermarks
                            } else {
                                current.sessionEpochHighWatermarks + (pairingScope to legacy.sessionEpoch)
                            },
                        nonceHighWatermarks = current.nonceHighWatermarks + scopedLegacyNonces,
                        revocationSequenceHighWatermarks =
                            if (legacy.revocationSequence == 0L) {
                                current.revocationSequenceHighWatermarks
                            } else {
                                current.revocationSequenceHighWatermarks +
                                    (pairingScope to legacy.revocationSequence)
                            },
                        legacySessionState = null,
                    )
                }

                // A newly authorized identity may use a new pairing scope, but
                // the unowned legacy counters stay durable instead of being reset.
                identityEpoch > legacy.ownerIdentityEpoch -> current

                else -> error("Legacy session security state cannot be attributed to this pairing")
            }
        if (resolved !== current) store.persist(resolved)
        return resolved
    }

    private companion object {
        const val NONCE_BYTES = 12
        const val SHA256_BYTES = 32
        val persistenceLock = Any()
    }
}

internal fun pairingSecurityScope(
    localDeviceId: String,
    pairingIdentifier: String,
): String {
    require(localDeviceId.isNotBlank() && pairingIdentifier.isNotBlank()) {
        "Local device ID and pairing identifier are required"
    }
    return MessageDigest
        .getInstance("SHA-256")
        .digest(
            localDeviceId.toByteArray(Charsets.UTF_8) +
                byteArrayOf(0) +
                pairingIdentifier.toByteArray(Charsets.UTF_8),
        )
        .toHex()
}

internal fun deviceSecurityScope(localDeviceId: String): String {
    require(localDeviceId.isNotBlank()) { "Local device ID must not be blank" }
    return MessageDigest
        .getInstance("SHA-256")
        .digest(localDeviceId.toByteArray(Charsets.UTF_8))
        .toHex()
}

private fun scopedNonceCounterKey(
    pairingScope: String,
    channel: Int,
    senderRole: Int,
    keyEpoch: Long,
): String = "$pairingScope:$channel:$senderRole:$keyEpoch"

private fun isScopeHash(value: String): Boolean =
    value.length == 64 && value.all { it in '0'..'9' || it in 'a'..'f' }

private fun isSHA256Hex(value: String): Boolean = isScopeHash(value)

internal data class DecodedSecurityPreferences(
    val state: DurableSecurityState,
    val migratedFromLegacy: Boolean,
)

internal fun DecodedSecurityPreferences.resolveAuthorizedIdentityKeyBinding(
    localDeviceId: String,
    loadExistingIdentity: (String, Long) -> AndroidPublicIdentity?,
): DurableSecurityState {
    val current = state
    if (!migratedFromLegacy || current.authorizedIdentityEpoch == 0L || current.authorizedIdentityKeyId != null) {
        return current
    }
    val identityEpoch = current.authorizedIdentityEpoch
    val identity = loadExistingIdentity(localDeviceId, identityEpoch) ?: return current
    check(identity.deviceId == localDeviceId && identity.keyEpoch == identityEpoch) {
        "Stored authorized identity does not match the migrated device and epoch; pair again"
    }
    val computedKeyId = MessageDigest.getInstance("SHA-256").digest(identity.signingPublicKey).toHex()
    check(
        isSHA256Hex(identity.keyId) &&
            MessageDigest.isEqual(computedKeyId.toByteArray(), identity.keyId.toByteArray()),
    ) {
        "Stored authorized identity key binding is invalid; pair again"
    }
    return current.copy(authorizedIdentityKeyId = identity.keyId)
}

internal object SecurityStatePreferenceCodec {
    private const val VERSION = 3
    private const val LEGACY_SCOPED_VERSION = 2
    private const val SCHEMA_VERSION = "schema_version"
    private const val DEVICE_SCOPE = "device_scope"
    private const val SESSION_PREFIX = "session."
    private const val REVOCATION_PREFIX = "revocation."
    private const val SCOPED_NONCE_PREFIX = "scoped_nonce."
    private const val LEGACY_SESSION_EPOCH = "session_epoch"
    private const val LEGACY_NONCE_PREFIX = "nonce."
    private const val LEGACY_PENDING = "legacy_pending"
    private const val LEGACY_OWNER_IDENTITY_EPOCH = "legacy_owner_identity_epoch"
    private const val LEGACY_REVOCATION_SEQUENCE = "legacy_revocation_sequence"
    private const val LEGACY_REVOKED = "legacy_revoked"
    private const val LEGACY_SCOPED_SESSION_EPOCH = "legacy_session_epoch"
    private const val LEGACY_SCOPED_NONCE_PREFIX = "legacy_nonce."
    private const val REVOCATION_SEQUENCE = "revocation_sequence"
    private const val REVOKED = "revoked"
    private const val ROTATION_NONCE_HASHES = "rotation_nonce_hashes"
    private const val IDENTITY_EPOCH_HIGH_WATERMARK = "identity_epoch_high_watermark"
    private const val AUTHORIZED_IDENTITY_EPOCH = "authorized_identity_epoch"
    private const val AUTHORIZED_IDENTITY_KEY_ID = "authorized_identity_key_id"

    private val baseGlobalKeys =
        setOf(
            REVOKED,
            ROTATION_NONCE_HASHES,
            IDENTITY_EPOCH_HIGH_WATERMARK,
            AUTHORIZED_IDENTITY_EPOCH,
        )
    private val version3GlobalKeys = baseGlobalKeys + AUTHORIZED_IDENTITY_KEY_ID
    private val legacyGlobalKeys = baseGlobalKeys + REVOCATION_SEQUENCE

    fun decode(
        values: Map<String, *>,
        expectedDeviceScope: String,
        allowEmptyInitialization: Boolean = false,
    ): DecodedSecurityPreferences {
        require(isScopeHash(expectedDeviceScope)) { "Device security scope is invalid" }
        if (SCHEMA_VERSION !in values) {
            check(values.isNotEmpty() || allowEmptyInitialization) {
                "Phase 3 security state is missing while durable security artifacts remain; pair again"
            }
            return DecodedSecurityPreferences(decodeLegacy(values), true)
        }
        return when (val version = values.requireInt(SCHEMA_VERSION)) {
            VERSION -> DecodedSecurityPreferences(decodeVersioned(values, expectedDeviceScope, version), false)
            LEGACY_SCOPED_VERSION -> DecodedSecurityPreferences(decodeVersioned(values, expectedDeviceScope, version), true)
            else -> error("Stored security state version $version is unsupported")
        }
    }

    fun encode(
        state: DurableSecurityState,
        deviceScope: String,
    ): Map<String, Any> {
        require(isScopeHash(deviceScope)) { "Device security scope is invalid" }
        validateState(state)
        val values =
            mutableMapOf<String, Any>(
                SCHEMA_VERSION to VERSION,
                DEVICE_SCOPE to deviceScope,
                REVOKED to state.revoked,
                ROTATION_NONCE_HASHES to state.usedRotationNonceHashes,
                IDENTITY_EPOCH_HIGH_WATERMARK to state.identityEpochHighWatermark,
                AUTHORIZED_IDENTITY_EPOCH to state.authorizedIdentityEpoch,
                AUTHORIZED_IDENTITY_KEY_ID to state.authorizedIdentityKeyId.orEmpty(),
                LEGACY_PENDING to (state.legacySessionState != null),
            )
        state.sessionEpochHighWatermarks.forEach { (scope, epoch) ->
            values[SESSION_PREFIX + scope] = epoch
        }
        state.revocationSequenceHighWatermarks.forEach { (scope, sequence) ->
            values[REVOCATION_PREFIX + scope] = sequence
        }
        state.nonceHighWatermarks.forEach { (key, sequence) ->
            values[SCOPED_NONCE_PREFIX + key] = sequence
        }
        state.legacySessionState?.let { legacy ->
            values[LEGACY_SCOPED_SESSION_EPOCH] = legacy.sessionEpoch
            values[LEGACY_OWNER_IDENTITY_EPOCH] = legacy.ownerIdentityEpoch
            values[LEGACY_REVOCATION_SEQUENCE] = legacy.revocationSequence
            values[LEGACY_REVOKED] = legacy.revoked
            legacy.nonceHighWatermarks.forEach { (key, sequence) ->
                values[LEGACY_SCOPED_NONCE_PREFIX + key] = sequence
            }
        }
        return values
    }

    private fun decodeLegacy(values: Map<String, *>): DurableSecurityState {
        check(
            values.keys.all {
                it in legacyGlobalKeys ||
                    it == LEGACY_SESSION_EPOCH ||
                    it.startsWith(LEGACY_NONCE_PREFIX)
            },
        ) {
            "Stored legacy security state contains unknown fields"
        }
        val sessionEpoch = values.optionalLong(LEGACY_SESSION_EPOCH)
        val revocationSequence = values.optionalLong(REVOCATION_SEQUENCE)
        val revoked = values.optionalBoolean(REVOKED)
        val identityEpochHighWatermark = values.optionalLong(IDENTITY_EPOCH_HIGH_WATERMARK)
        val authorizedIdentityEpoch = values.optionalLong(AUTHORIZED_IDENTITY_EPOCH)
        val nonceHighWatermarks =
            values.entries
                .filter { it.key.startsWith(LEGACY_NONCE_PREFIX) }
                .associate { entry ->
                    entry.key.removePrefix(LEGACY_NONCE_PREFIX).also(::requireLegacyNonceKey) to
                        entry.requireLong()
                }
        val rotationHashes = values.optionalStringSet(ROTATION_NONCE_HASHES)
        val hasLegacySessionState =
            sessionEpoch > 0 || nonceHighWatermarks.isNotEmpty() || revocationSequence > 0 || revoked
        val state =
            DurableSecurityState(
                revoked = revoked,
                usedRotationNonceHashes = rotationHashes,
                identityEpochHighWatermark = identityEpochHighWatermark,
                authorizedIdentityEpoch = authorizedIdentityEpoch,
                legacySessionState =
                    if (hasLegacySessionState) {
                        check(authorizedIdentityEpoch > 0) {
                            "Stored legacy session state has no authorized identity owner"
                        }
                        LegacySessionSecurityState(
                            sessionEpoch = sessionEpoch,
                            nonceHighWatermarks = nonceHighWatermarks,
                            ownerIdentityEpoch = authorizedIdentityEpoch,
                            revocationSequence = revocationSequence,
                            revoked = revoked,
                        )
                    } else {
                        null
                    },
            )
        validateState(state)
        return state
    }

    private fun decodeVersioned(
        values: Map<String, *>,
        expectedDeviceScope: String,
        version: Int,
    ): DurableSecurityState {
        check(values.requireString(DEVICE_SCOPE) == expectedDeviceScope) {
            "Stored security state belongs to another local device identity"
        }
        val requiredGlobalKeys = if (version == VERSION) version3GlobalKeys else baseGlobalKeys
        requiredGlobalKeys.forEach { check(it in values) { "Stored security state is missing $it" } }
        check(LEGACY_PENDING in values) { "Stored security state is missing legacy migration status" }
        val legacyPending = values.requireBoolean(LEGACY_PENDING)
        val allowedExact = requiredGlobalKeys + setOf(SCHEMA_VERSION, DEVICE_SCOPE, LEGACY_PENDING)
        check(
            values.keys.all { key ->
                key in allowedExact ||
                    key.startsWith(SESSION_PREFIX) ||
                    key.startsWith(REVOCATION_PREFIX) ||
                    key.startsWith(SCOPED_NONCE_PREFIX) ||
                    legacyPending &&
                    (
                        key in
                            setOf(
                                LEGACY_SCOPED_SESSION_EPOCH,
                                LEGACY_OWNER_IDENTITY_EPOCH,
                                LEGACY_REVOCATION_SEQUENCE,
                                LEGACY_REVOKED,
                            ) || key.startsWith(LEGACY_SCOPED_NONCE_PREFIX)
                    )
            },
        ) { "Stored security state contains unknown fields" }
        val sessions =
            values.entries
                .filter { it.key.startsWith(SESSION_PREFIX) }
                .associate { entry ->
                    entry.key.removePrefix(SESSION_PREFIX).also { check(isScopeHash(it)) } to entry.requireLong()
                }
        val nonces =
            values.entries
                .filter { it.key.startsWith(SCOPED_NONCE_PREFIX) }
                .associate { entry ->
                    entry.key.removePrefix(SCOPED_NONCE_PREFIX).also(::requireScopedNonceKey) to entry.requireLong()
                }
        val revocations =
            values.entries
                .filter { it.key.startsWith(REVOCATION_PREFIX) }
                .associate { entry ->
                    entry.key.removePrefix(REVOCATION_PREFIX).also { check(isScopeHash(it)) } to
                        entry.requireLong()
                }
        val legacy =
            if (legacyPending) {
                listOf(
                    LEGACY_SCOPED_SESSION_EPOCH,
                    LEGACY_OWNER_IDENTITY_EPOCH,
                    LEGACY_REVOCATION_SEQUENCE,
                    LEGACY_REVOKED,
                ).forEach { check(it in values) { "Stored legacy migration state is incomplete" } }
                LegacySessionSecurityState(
                    sessionEpoch = values.requireLong(LEGACY_SCOPED_SESSION_EPOCH),
                    nonceHighWatermarks =
                        values.entries
                            .filter { it.key.startsWith(LEGACY_SCOPED_NONCE_PREFIX) }
                            .associate { entry ->
                                entry.key.removePrefix(LEGACY_SCOPED_NONCE_PREFIX)
                                    .also(::requireLegacyNonceKey) to entry.requireLong()
                            },
                    ownerIdentityEpoch = values.requireLong(LEGACY_OWNER_IDENTITY_EPOCH),
                    revocationSequence = values.requireLong(LEGACY_REVOCATION_SEQUENCE),
                    revoked = values.requireBoolean(LEGACY_REVOKED),
                )
            } else {
                null
            }
        val state =
            DurableSecurityState(
                sessionEpochHighWatermarks = sessions,
                revocationSequenceHighWatermarks = revocations,
                revoked = values.requireBoolean(REVOKED),
                nonceHighWatermarks = nonces,
                usedRotationNonceHashes = values.requireStringSet(ROTATION_NONCE_HASHES),
                identityEpochHighWatermark = values.requireLong(IDENTITY_EPOCH_HIGH_WATERMARK),
                authorizedIdentityEpoch = values.requireLong(AUTHORIZED_IDENTITY_EPOCH),
                authorizedIdentityKeyId =
                    if (version == VERSION) {
                        values.requireString(AUTHORIZED_IDENTITY_KEY_ID).ifEmpty { null }
                    } else {
                        null
                    },
                legacySessionState = legacy,
            )
        validateState(state)
        return state
    }

    private fun validateState(state: DurableSecurityState) {
        check(
            state.identityEpochHighWatermark in 0 until Long.MAX_VALUE &&
                state.authorizedIdentityEpoch in 0 until Long.MAX_VALUE &&
                state.authorizedIdentityEpoch <= state.identityEpochHighWatermark &&
                (state.authorizedIdentityKeyId == null || isSHA256Hex(state.authorizedIdentityKeyId)) &&
                (state.authorizedIdentityEpoch > 0 || state.authorizedIdentityKeyId == null) &&
                state.sessionEpochHighWatermarks.all { (scope, epoch) ->
                    isScopeHash(scope) && epoch in 1 until Long.MAX_VALUE
                } &&
                state.revocationSequenceHighWatermarks.all { (scope, sequence) ->
                    isScopeHash(scope) && sequence in 1 until Long.MAX_VALUE
                } &&
                state.nonceHighWatermarks.all { (key, sequence) ->
                    runCatching { requireScopedNonceKey(key) }.isSuccess && sequence in 1 until Long.MAX_VALUE
                },
        ) { "Stored monotonic security state is invalid" }
        check(
            state.usedRotationNonceHashes.all(::isSHA256Hex),
        ) {
            "Stored rotation nonce state is invalid"
        }
        state.legacySessionState?.let { legacy ->
            check(
                legacy.sessionEpoch in 0 until Long.MAX_VALUE &&
                    legacy.ownerIdentityEpoch in 1 until Long.MAX_VALUE &&
                    legacy.revocationSequence in 0 until Long.MAX_VALUE &&
                    legacy.nonceHighWatermarks.all { (key, sequence) ->
                        runCatching { requireLegacyNonceKey(key) }.isSuccess && sequence in 0 until Long.MAX_VALUE
                    },
            ) { "Stored legacy session security state is invalid" }
            if (state.authorizedIdentityEpoch == legacy.ownerIdentityEpoch) {
                check(state.revoked == legacy.revoked) {
                    "Stored legacy revocation state disagrees with its identity owner"
                }
            }
        }
    }

    private fun requireLegacyNonceKey(key: String) {
        val parts = key.split(':')
        check(parts.size == 3 && parts.allIndexedPositive()) { "Stored legacy nonce key is invalid" }
    }

    private fun requireScopedNonceKey(key: String) {
        val parts = key.split(':')
        check(parts.size == 4 && isScopeHash(parts[0]) && parts.drop(1).allIndexedPositive()) {
            "Stored scoped nonce key is invalid"
        }
    }

    private fun List<String>.allIndexedPositive(): Boolean =
        all { value -> value.toLongOrNull()?.let { it in 1 until Long.MAX_VALUE } == true }

    private fun Map<String, *>.optionalLong(key: String): Long =
        if (key in this) requireLong(key) else 0

    private fun Map<String, *>.requireLong(key: String): Long =
        (get(key) as? Long) ?: error("Stored security field $key has the wrong type")

    private fun Map.Entry<String, *>.requireLong(): Long =
        (value as? Long) ?: error("Stored security field $key has the wrong type")

    private fun Map.Entry<String, *>.requireStringSet(): Set<String> {
        val raw = value as? Set<*> ?: error("Stored security field $key has the wrong type")
        check(raw.all { it is String }) { "Stored security field $key has invalid values" }
        return raw.filterIsInstance<String>().toSet()
    }

    private fun Map<String, *>.requireInt(key: String): Int =
        (get(key) as? Int) ?: error("Stored security field $key has the wrong type")

    private fun Map<String, *>.optionalBoolean(key: String): Boolean =
        if (key in this) requireBoolean(key) else false

    private fun Map<String, *>.requireBoolean(key: String): Boolean =
        (get(key) as? Boolean) ?: error("Stored security field $key has the wrong type")

    private fun Map<String, *>.requireString(key: String): String =
        (get(key) as? String) ?: error("Stored security field $key has the wrong type")

    private fun Map<String, *>.optionalStringSet(key: String): Set<String> =
        if (key in this) requireStringSet(key) else emptySet()

    private fun Map<String, *>.requireStringSet(key: String): Set<String> {
        val raw = get(key) as? Set<*> ?: error("Stored security field $key has the wrong type")
        check(raw.all { it is String }) { "Stored security field $key has invalid values" }
        return raw.filterIsInstance<String>().toSet()
    }
}

/** SharedPreferences contains counters and revocation status only, never keys. */
class SharedPreferencesSecurityStateStore(
    context: Context,
    private val localDeviceId: String,
    private val loadExistingIdentity: (String, Long) -> AndroidPublicIdentity? = { deviceId, identityEpoch ->
        AndroidDeviceIdentityStore().loadExisting(deviceId, identityEpoch)?.publicIdentity
    },
) : SecurityStateStore {
    private val applicationContext = context.applicationContext
    private val preferences: SharedPreferences =
        applicationContext.getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)
    private val deviceScope = deviceSecurityScope(localDeviceId)

    override fun load(): DurableSecurityState {
        val storedValues = preferences.all
        val decoded =
            SecurityStatePreferenceCodec.decode(
                storedValues,
                deviceScope,
                allowEmptyInitialization =
                    storedValues.isEmpty() && !hasDurableSecurityArtifacts(applicationContext),
            )
        val resolved = decoded.resolveAuthorizedIdentityKeyBinding(localDeviceId, loadExistingIdentity)
        if (decoded.migratedFromLegacy) persist(resolved)
        return resolved
    }

    override fun persist(state: DurableSecurityState) {
        val values = SecurityStatePreferenceCodec.encode(state, deviceScope)
        val editor = preferences.edit().clear()
        values.forEach { (key, value) ->
            when (value) {
                is Boolean -> editor.putBoolean(key, value)
                is Int -> editor.putInt(key, value)
                is Long -> editor.putLong(key, value)
                is String -> editor.putString(key, value)
                is Set<*> -> editor.putStringSet(key, value.filterIsInstance<String>().toSet())
                else -> error("Unsupported stored security field type")
            }
        }
        check(editor.commit()) { "Failed to durably commit Phase 3 security state" }
    }

    companion object {
        const val PREFERENCES_NAME = "phase3_security_state"
        private const val SECRET_PREFERENCES_NAME = "phase3_security_secrets"
        private const val PROFILE_PREFERENCES_NAME = "phase3_internet_profile"
        private const val IDENTITY_ALIAS_PREFIX = "dev.telemachus.display.phase3.identity.v1."
        private const val SECRET_WRAPPING_ALIAS = "dev.telemachus.display.phase3.secret-wrapping.v1"

        private fun hasDurableSecurityArtifacts(context: Context): Boolean {
            if (context.getSharedPreferences(SECRET_PREFERENCES_NAME, Context.MODE_PRIVATE).all.isNotEmpty()) return true
            if (context.getSharedPreferences(PROFILE_PREFERENCES_NAME, Context.MODE_PRIVATE).all.isNotEmpty()) return true
            val aliases =
                KeyStore
                    .getInstance("AndroidKeyStore")
                    .apply { load(null) }
                    .aliases()
            return aliases.asSequence().any { alias ->
                alias == SECRET_WRAPPING_ALIAS || alias.startsWith(IDENTITY_ALIAS_PREFIX)
            }
        }
    }
}

private fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it) }
