package dev.telemachus.display

import android.content.Context
import android.content.SharedPreferences
import java.security.MessageDigest

internal data class PendingPairingIdentityAliasMarker(
    val deviceId: String,
    val identityEpoch: Long,
    val aliasIdentity: String,
) {
    init {
        require(deviceId.isNotBlank()) { "Pending pairing identity device ID is required" }
        require(identityEpoch > 0) { "Pending pairing identity epoch must be positive" }
        require(aliasIdentity == expectedAliasIdentity(deviceId, identityEpoch)) {
            "Pending pairing identity alias does not match its device ID and epoch"
        }
    }

    companion object {
        fun create(deviceId: String, identityEpoch: Long): PendingPairingIdentityAliasMarker =
            PendingPairingIdentityAliasMarker(
                deviceId = deviceId,
                identityEpoch = identityEpoch,
                aliasIdentity = expectedAliasIdentity(deviceId, identityEpoch),
            )

        private fun expectedAliasIdentity(deviceId: String, identityEpoch: Long): String {
            require(deviceId.isNotBlank()) { "Pending pairing identity device ID is required" }
            require(identityEpoch > 0) { "Pending pairing identity epoch must be positive" }
            val deviceHash =
                MessageDigest
                    .getInstance("SHA-256")
                    .digest(deviceId.toByteArray(Charsets.UTF_8))
                    .joinToString("") { "%02x".format(it) }
            return "$IDENTITY_ALIAS_PREFIX.$deviceHash.$identityEpoch"
        }
    }
}

internal interface PendingPairingIdentityAliasPersistence {
    fun load(): PendingPairingIdentityAliasMarker?

    fun persist(marker: PendingPairingIdentityAliasMarker)

    fun clear(marker: PendingPairingIdentityAliasMarker)
}

internal class SharedPreferencesPendingPairingIdentityAliasPersistence(
    context: Context,
) : PendingPairingIdentityAliasPersistence {
    private val preferences: SharedPreferences =
        context.applicationContext.getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)

    @Synchronized
    override fun load(): PendingPairingIdentityAliasMarker? {
        val presentKeys = MARKER_KEYS.count(preferences::contains)
        if (presentKeys == 0) return null
        check(presentKeys == MARKER_KEYS.size) { "Pending pairing identity marker is incomplete" }
        check(preferences.getInt(VERSION_KEY, 0) == MARKER_VERSION) {
            "Pending pairing identity marker version is unsupported"
        }
        return PendingPairingIdentityAliasMarker(
            deviceId = checkNotNull(preferences.getString(DEVICE_ID_KEY, null)) {
                "Pending pairing identity device ID is missing"
            },
            identityEpoch = preferences.getLong(IDENTITY_EPOCH_KEY, 0),
            aliasIdentity = checkNotNull(preferences.getString(ALIAS_IDENTITY_KEY, null)) {
                "Pending pairing identity alias is missing"
            },
        )
    }

    @Synchronized
    override fun persist(marker: PendingPairingIdentityAliasMarker) {
        val existing = load()
        check(existing == null || existing == marker) { "Another pairing identity alias is already pending cleanup" }
        check(
            preferences
                .edit()
                .putInt(VERSION_KEY, MARKER_VERSION)
                .putString(DEVICE_ID_KEY, marker.deviceId)
                .putLong(IDENTITY_EPOCH_KEY, marker.identityEpoch)
                .putString(ALIAS_IDENTITY_KEY, marker.aliasIdentity)
                .commit(),
        ) {
            "Failed to persist pending pairing identity cleanup marker"
        }
    }

    @Synchronized
    override fun clear(marker: PendingPairingIdentityAliasMarker) {
        val existing = load() ?: return
        check(existing == marker) { "Pending pairing identity cleanup marker changed ownership" }
        check(
            preferences
                .edit()
                .remove(VERSION_KEY)
                .remove(DEVICE_ID_KEY)
                .remove(IDENTITY_EPOCH_KEY)
                .remove(ALIAS_IDENTITY_KEY)
                .commit(),
        ) {
            "Failed to clear pending pairing identity cleanup marker"
        }
    }

    companion object {
        private const val PREFERENCES_NAME = "pending_pairing_identity_alias"
        private const val MARKER_VERSION = 1
        private const val VERSION_KEY = "version"
        private const val DEVICE_ID_KEY = "device_id"
        private const val IDENTITY_EPOCH_KEY = "identity_epoch"
        private const val ALIAS_IDENTITY_KEY = "alias_identity"
        private val MARKER_KEYS = setOf(VERSION_KEY, DEVICE_ID_KEY, IDENTITY_EPOCH_KEY, ALIAS_IDENTITY_KEY)
    }
}

internal class PendingPairingIdentityAlias private constructor(
    private val marker: PendingPairingIdentityAliasMarker,
    private val persistence: PendingPairingIdentityAliasPersistence,
    private val deleteIdentity: (String, Long) -> Unit,
) : AutoCloseable {
    private var committed = false
    private var cleanupComplete = false

    fun commit() {
        check(!cleanupComplete) { "Pairing identity alias was already deleted" }
        committed = true
        persistence.clear(marker)
    }

    override fun close() {
        if (committed || cleanupComplete) return
        deleteIdentity(marker.deviceId, marker.identityEpoch)
        persistence.clear(marker)
        cleanupComplete = true
    }

    fun closeWithSuppressed(failure: Throwable) {
        try {
            close()
        } catch (cleanupFailure: Throwable) {
            failure.addSuppressed(cleanupFailure)
        }
    }

    companion object {
        fun create(
            persistence: PendingPairingIdentityAliasPersistence,
            deviceId: String,
            identityEpoch: Long,
            deleteIdentity: (String, Long) -> Unit,
        ): PendingPairingIdentityAlias {
            val marker = PendingPairingIdentityAliasMarker.create(deviceId, identityEpoch)
            persistence.persist(marker)
            return PendingPairingIdentityAlias(marker, persistence, deleteIdentity)
        }
    }
}

internal fun recoverPendingPairingIdentityAlias(
    persistence: PendingPairingIdentityAliasPersistence,
    isCommittedIdentity: (PendingPairingIdentityAliasMarker) -> Boolean,
    deleteIdentity: (String, Long) -> Unit,
): Boolean {
    val marker = persistence.load() ?: return false
    if (!isCommittedIdentity(marker)) {
        deleteIdentity(marker.deviceId, marker.identityEpoch)
    }
    persistence.clear(marker)
    return true
}

private const val IDENTITY_ALIAS_PREFIX = "dev.telemachus.display.phase3.identity.v1"
