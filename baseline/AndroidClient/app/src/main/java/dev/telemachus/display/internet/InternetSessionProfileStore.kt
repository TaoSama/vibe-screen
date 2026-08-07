package dev.telemachus.display.internet

import android.annotation.SuppressLint
import android.content.Context
import android.content.SharedPreferences
import android.content.pm.ApplicationInfo
import com.google.gson.JsonArray
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import com.google.gson.stream.JsonReader
import com.google.gson.stream.JsonToken
import com.google.gson.stream.JsonWriter
import dev.telemachus.display.internet.security.AndroidSecretStore
import dev.telemachus.display.internet.security.AndroidStoredInternetSessionFactory
import dev.telemachus.display.internet.security.InternetPairingPublicMetadata
import dev.telemachus.display.internet.security.InternetPairingIdentity
import dev.telemachus.display.internet.security.SecurityTranscript
import dev.telemachus.display.internet.security.SensitiveBufferObserver
import dev.telemachus.display.internet.security.TranscriptDigestUpdater
import dev.telemachus.display.internet.security.verify
import java.net.URI
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.io.StringReader
import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.util.Base64

/** Non-secret, persisted part of a short-lived Internet session lease. */
data class StoredInternetSessionProfile(
    val pairingIdentifier: String,
    val pinnedHostId: String,
    val pinnedDeviceId: String,
    val leaseDeviceKeyId: String,
    val signalingUrl: String,
    val signalingSessionId: String,
    val authoritativeSessionEpoch: Long,
    val hostIdentityEpoch: Long,
    val deviceIdentityEpoch: Long,
    val expiresAtUnixSeconds: Long,
    val transcriptContext: ByteArray,
    val protocolSessionId: ByteArray,
    val iceServerUrls: List<List<String>>,
    val allowInsecureForTesting: Boolean,
    val leaseHostKeyId: String,
    val leaseSignature: ByteArray,
) {
    val identityEpoch: Long
        get() = deviceIdentityEpoch
}

internal class ImportedInternetSecrets(
    val signalingToken: DestroyableUtf8,
    val turnCredentials: List<Pair<DestroyableUtf8?, DestroyableUtf8?>>,
) : AutoCloseable {
    override fun close() {
        signalingToken.close()
        turnCredentials.forEach { (username, credential) ->
            username?.close()
            credential?.close()
        }
    }

    override fun toString(): String = "ImportedInternetSecrets(<redacted>)"
}

internal data class DecodedInternetProfile(
    val profile: StoredInternetSessionProfile,
    val secrets: ImportedInternetSecrets,
) : AutoCloseable {
    override fun close() = secrets.close()
}

private sealed interface StoredPairingRecord {
    val pairingIdentifier: String
    val hostIdentity: InternetPairingIdentity
    val localDeviceId: String
    val localIdentityEpoch: Long
    val sessionContext: ByteArray
}

private data class StoredPairingBinding(
    override val pairingIdentifier: String,
    override val hostIdentity: InternetPairingIdentity,
    val localIdentity: InternetPairingIdentity,
    override val sessionContext: ByteArray,
) : StoredPairingRecord {
    override val localDeviceId: String = localIdentity.deviceId
    override val localIdentityEpoch: Long = localIdentity.keyEpoch
}

private data class LegacyStoredPairingBinding(
    override val pairingIdentifier: String,
    override val hostIdentity: InternetPairingIdentity,
    override val localDeviceId: String,
    override val localIdentityEpoch: Long,
    override val sessionContext: ByteArray,
) : StoredPairingRecord

private data class PendingAuthenticatedRevocation(
    val pairingIdentifier: String,
    val reason: String,
)

internal object InternetCredentialOwnershipPolicy {
    fun blocksMutation(
        targetPairingIdentifier: String?,
        verifiedPairingIdentifier: String?,
        profilePairingIdentifier: String?,
        revokedPairingIdentifier: String?,
        hasPendingAuthenticatedRevocation: Boolean,
        hasPendingRevocationCleanup: Boolean,
    ): Boolean =
        hasPendingAuthenticatedRevocation ||
            hasPendingRevocationCleanup ||
            targetPairingIdentifier != null &&
            (
                revokedPairingIdentifier == targetPairingIdentifier ||
                    verifiedPairingIdentifier != null && verifiedPairingIdentifier != targetPairingIdentifier ||
                    profilePairingIdentifier != null && profilePairingIdentifier != targetPairingIdentifier
            )
}

internal class DeferredSecretCleanupPending {
    private val values = mutableSetOf<String>()

    @Synchronized fun merge(incoming: Set<String>) { values += incoming }
    @Synchronized fun enqueue(value: String) { values += value }
    @Synchronized fun replaceAfterDurableCommit(remaining: Set<String>) { values.clear(); values += remaining }
    @Synchronized fun snapshot(): Set<String> = values.toSet()
}

internal interface InternetProfilePreferences {
    fun getString(key: String, defaultValue: String?): String?
    fun getStringSet(key: String, defaultValue: Set<String>?): Set<String>?
    fun edit(): InternetProfilePreferencesEditor
}

internal interface InternetProfilePreferencesEditor {
    fun putString(key: String, value: String): InternetProfilePreferencesEditor
    fun putStringSet(key: String, value: Set<String>): InternetProfilePreferencesEditor
    fun remove(key: String): InternetProfilePreferencesEditor
    fun commit(): Boolean
}

private class AndroidInternetProfilePreferences(
    private val delegate: SharedPreferences,
) : InternetProfilePreferences {
    override fun getString(key: String, defaultValue: String?): String? = delegate.getString(key, defaultValue)
    override fun getStringSet(key: String, defaultValue: Set<String>?): Set<String>? = delegate.getStringSet(key, defaultValue)
    override fun edit(): InternetProfilePreferencesEditor = AndroidInternetProfilePreferencesEditor(delegate.edit())
}

private class AndroidInternetProfilePreferencesEditor(
    private val delegate: SharedPreferences.Editor,
) : InternetProfilePreferencesEditor {
    override fun putString(key: String, value: String): InternetProfilePreferencesEditor = apply { delegate.putString(key, value) }
    override fun putStringSet(key: String, value: Set<String>): InternetProfilePreferencesEditor = apply { delegate.putStringSet(key, value) }
    override fun remove(key: String): InternetProfilePreferencesEditor = apply { delegate.remove(key) }
    override fun commit(): Boolean = delegate.commit()
}

internal interface InternetProfileSecretStore {
    fun persist(name: String, secret: ByteArray)
    fun load(name: String): ByteArray?
    fun delete(name: String)
}

private class AndroidInternetProfileSecretStore(
    private val delegate: AndroidSecretStore,
) : InternetProfileSecretStore {
    override fun persist(name: String, secret: ByteArray) = delegate.persist(name, secret)
    override fun load(name: String): ByteArray? = delegate.load(name)
    override fun delete(name: String) = delegate.delete(name)
}

/**
 * Splits imported pairing material into ordinary preferences and AndroidKeyStore-wrapped records.
 * Tokens, TURN credentials, and pairing keys are never returned by [exportNonSecretSummary].
 */
class InternetSessionProfileStore internal constructor(
    private val preferences: InternetProfilePreferences,
    private val debuggable: Boolean,
    private val secretStore: InternetProfileSecretStore,
    private val nowUnixSeconds: () -> Long = { System.currentTimeMillis() / 1_000 },
) {
    constructor(
        context: Context,
        secretStore: AndroidSecretStore = AndroidSecretStore(context.applicationContext),
    ) : this(
        AndroidInternetProfilePreferences(context.getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)),
        context.applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE != 0,
        AndroidInternetProfileSecretStore(secretStore),
    )

    private val inMemoryDeferredCleanup = DeferredSecretCleanupPending()

    fun import(
        json: String,
        storedSessionFactory: AndroidStoredInternetSessionFactory,
        revocationCoordinator: InternetProductRevocationCoordinator,
    ): StoredInternetSessionProfile {
        retryDeferredCredentialCleanup()
        val decoded = InternetSessionProfileCodec.decode(json, debuggable)
        return try {
            revocationCoordinator.withCredentialMutationAdmission(
                durableBlock = {
                    hasDurableCredentialMutationBlock(decoded.profile.pairingIdentifier) ||
                        storedSessionFactory.hasPendingPairingPersistenceCleanup()
                },
            ) {
                val pairing = loadVerifiedPairingBinding() ?: throw IllegalStateException("Complete signed pairing before importing a lease")
                require(decoded.profile.pairingIdentifier == pairing.pairingIdentifier) { "Lease pairing does not match the verified Mac" }
                require(decoded.profile.pinnedHostId == pairing.hostIdentity.deviceId) { "Lease host identity does not match the verified Mac" }
                require(decoded.profile.hostIdentityEpoch == pairing.hostIdentity.keyEpoch) { "Lease host identity epoch does not match the paired identity" }
                require(decoded.profile.pinnedDeviceId == pairing.localIdentity.deviceId) { "Lease device identity does not match the paired identity" }
                require(decoded.profile.leaseDeviceKeyId == pairing.localIdentity.keyId) { "Lease device signing key does not match the paired identity" }
                require(decoded.profile.deviceIdentityEpoch == pairing.localIdentityEpoch) { "Lease local identity epoch does not match the paired identity" }
                require(nowUnixSeconds() < decoded.profile.expiresAtUnixSeconds) { "Internet session lease has expired; request a fresh lease" }
                require(storedSessionFactory.localDeviceId == pairing.localDeviceId) {
                    "Lease lifecycle state does not belong to the paired local identity"
                }
                require(decoded.profile.transcriptContext.contentEquals(pairing.sessionContext)) {
                    "Lease transcript context does not match signed pairing"
                }
                verifySignedLease(decoded, pairing)
                storedSessionFactory.withFreshSessionEpochCandidate(
                    pairingIdentifier = decoded.profile.pairingIdentifier,
                    identity = pairing.localIdentity,
                    sessionEpoch = decoded.profile.authoritativeSessionEpoch,
                ) {
                    val current = loadPublicProfile()
                    if (current != null) {
                        require(decoded.profile.authoritativeSessionEpoch > current.authoritativeSessionEpoch) {
                            "A replacement Internet lease must use a strictly newer session epoch"
                        }
                    }
                    val encrypted = InternetSessionProfileCodec.encodeSecrets(decoded.secrets)
                    try {
                        secretStore.persist(profileSecretName(decoded.profile), encrypted)
                    } finally {
                        encrypted.fill(0)
                    }
                    val newSecretName = profileSecretName(decoded.profile)
                    val oldSecretName = current?.let(::profileSecretName)?.takeIf { it != newSecretName }
                    val cleanupQueue = oldSecretName?.let { enqueueDeferredSecretCleanup(loadDeferredSecretCleanup(), it) }
                        ?: loadDeferredSecretCleanup()
                    val committed =
                        commitProfileReplacement(
                            cleanupQueue = cleanupQueue,
                            commitPointerAndCleanup = { queued ->
                                val editor =
                                    preferences
                                        .edit()
                                        .putString(PROFILE_KEY, InternetSessionProfileCodec.encodePublic(decoded.profile))
                                if (queued.isEmpty()) editor.remove(DEFERRED_SECRET_CLEANUP_KEY) else {
                                    editor.putStringSet(DEFERRED_SECRET_CLEANUP_KEY, queued)
                                }
                                editor.commit()
                            },
                            rollbackNewSecret = { secretStore.delete(newSecretName) },
                        )
                    if (!committed) {
                        error("Failed to persist the Internet session profile")
                    }
                    inMemoryDeferredCleanup.replaceAfterDurableCommit(cleanupQueue)
                    retryDeferredCredentialCleanup()
                    decoded.profile
                }
            }
        } finally {
            decoded.close()
        }
    }

    fun loadLease(forceRelay: Boolean): InternetProductSessionLease? {
        retryDeferredCredentialCleanup()
        val profile = loadPublicProfile() ?: return null
        val pairing = loadVerifiedPairingBinding() ?: return null
        check(profile.pairingIdentifier == pairing.pairingIdentifier && profile.pinnedHostId == pairing.hostIdentity.deviceId) {
            "Stored Internet lease is not bound to the verified pairing"
        }
        check(profile.hostIdentityEpoch == pairing.hostIdentity.keyEpoch &&
            profile.pinnedDeviceId == pairing.localIdentity.deviceId &&
            profile.leaseDeviceKeyId == pairing.localIdentity.keyId &&
            profile.deviceIdentityEpoch == pairing.localIdentityEpoch &&
            profile.transcriptContext.contentEquals(pairing.sessionContext)) {
            "Stored Internet lease identity binding is invalid"
        }
        check(nowUnixSeconds() < profile.expiresAtUnixSeconds) {
            "Internet session lease has expired; request a fresh lease"
        }
        check(!isRevoked(profile.pairingIdentifier)) { "This paired Mac is locally revoked" }
        val encrypted = secretStore.load(profileSecretName(profile)) ?: return null
        val secrets =
            try {
                InternetSessionProfileCodec.decodeSecrets(encrypted, profile.iceServerUrls.size)
            } finally {
                encrypted.fill(0)
            }
        val iceServers = mutableListOf<IceServer>()
        var signaling: SignalingConfiguration? = null
        try {
            verifySignedLease(DecodedInternetProfile(profile, secrets), pairing)
            profile.iceServerUrls.forEachIndexed { index, urls ->
                val credential = secrets.turnCredentials[index]
                iceServers += IceServer(urls, credential.first?.copy(), credential.second?.copy())
            }
            signaling =
                SignalingConfiguration(
                    baseUrl = profile.signalingUrl,
                    bearerTokenSecret = secrets.signalingToken.copy(),
                    role = PeerRole.DEVICE,
                    allowInsecureForTesting = profile.allowInsecureForTesting,
                )
            return InternetProductSessionLease(
                pairingIdentifier = profile.pairingIdentifier,
                pinnedHostId = profile.pinnedHostId,
                signalingSessionId = profile.signalingSessionId,
                authoritativeSessionEpoch = profile.authoritativeSessionEpoch,
                identityEpoch = profile.deviceIdentityEpoch,
                localIdentity = pairing.localIdentity,
                transcriptContext = profile.transcriptContext.copyOf(),
                protocolSessionId = profile.protocolSessionId.copyOf(),
                iceServers = iceServers,
                signaling = signaling,
                iceTransportPolicy = if (forceRelay) IceTransportPolicy.RELAY_ONLY else IceTransportPolicy.ALL,
            )
        } catch (failure: Throwable) {
            signaling?.close()
            iceServers.forEach(IceServer::close)
            throw failure
        } finally {
            secrets.close()
        }
    }

    @SuppressLint("ApplySharedPref")
    internal fun recordVerifiedPairing(
        permit: InternetProductCredentialMutationPermit,
        metadata: InternetPairingPublicMetadata,
        storedSessionFactory: AndroidStoredInternetSessionFactory,
    ) {
        permit.requireActive()
        require(!hasDurableCredentialMutationBlock(metadata.pairingIdentifier)) { "This Mac pairing is locally revoked" }
        val context = requireNotNull(metadata.sessionContext) { "Completed pairing must include a session context" }
        val value =
            JsonObject().apply {
                addProperty("version", PAIRING_VERSION)
                addProperty("pairing_id", metadata.pairingIdentifier)
                addProperty("host_device_id", metadata.hostIdentity.deviceId)
                addProperty("host_key_id", metadata.hostIdentity.keyId)
                addProperty("host_identity_epoch", metadata.hostIdentity.keyEpoch)
                addProperty("host_signature_algorithm", metadata.hostIdentity.signatureAlgorithm)
                addProperty("host_signing_public_key", Base64.getEncoder().encodeToString(metadata.hostIdentity.signingPublicKey))
                addProperty("local_device_id", metadata.deviceIdentity.deviceId)
                addProperty("local_key_id", metadata.deviceIdentity.keyId)
                addProperty("local_identity_epoch", metadata.deviceIdentity.keyEpoch)
                addProperty("local_signature_algorithm", metadata.deviceIdentity.signatureAlgorithm)
                addProperty("local_signing_public_key", Base64.getEncoder().encodeToString(metadata.deviceIdentity.signingPublicKey))
                addProperty("session_context", Base64.getEncoder().encodeToString(context))
            }.toString()
        storedSessionFactory.completePairingPersistence(
            pairingIdentifier = metadata.pairingIdentifier,
            commitBusinessState = {
                storedSessionFactory.authorizeIdentity(metadata.deviceIdentity)
                check(preferences.edit().putString(PAIRING_KEY, value).commit()) {
                    "Failed to persist verified pairing metadata"
                }
            },
            cleanupBusinessState = { removePairingBindingIfMatches(permit, metadata.pairingIdentifier) },
        )
    }

    fun hasVerifiedPairing(): Boolean = loadPairingRecord() != null

    fun verifiedPairingIdentifier(): String? = loadPairingRecord()?.pairingIdentifier

    fun verifiedLocalIdentityEpoch(): Long? = loadPairingRecord()?.localIdentityEpoch

    fun verifiedHostKeyFingerprint(): String? = loadPairingRecord()?.hostIdentity?.keyId?.take(FINGERPRINT_CHARACTERS)

    fun markRevoked(pairingIdentifier: String) {
        InternetProductAdmissionGate.withLock {
            check(
                preferences
                    .edit()
                    .putString(REVOKED_PAIRING_KEY, pairingIdentifier)
                    .remove(PENDING_AUTHENTICATED_REVOCATION_KEY)
                    .commit(),
            ) {
                "Failed to persist the local revocation tombstone"
            }
        }
    }

    @SuppressLint("ApplySharedPref")
    fun persistPendingAuthenticatedRevocation(pairingIdentifier: String, reason: String) {
        InternetProductAdmissionGate.withLock {
            require(reason.isNotBlank()) { "Authenticated revocation reason is required" }
            require(verifiedPairingIdentifier() == pairingIdentifier) { "Authenticated revocation targets another pairing" }
            val requested = PendingAuthenticatedRevocation(pairingIdentifier, reason)
            val existing = loadPendingAuthenticatedRevocation()
            require(existing == null || existing == requested) { "Another authenticated revocation is already pending" }
            if (existing != null || preferences.getString(REVOKED_PAIRING_KEY, null) == pairingIdentifier) return@withLock
            check(
                preferences
                    .edit()
                    .putString(PENDING_AUTHENTICATED_REVOCATION_KEY, encodePendingAuthenticatedRevocation(requested))
                    .commit(),
            ) { "Failed to persist pending authenticated revocation" }
        }
    }

    @SuppressLint("ApplySharedPref")
    fun markAuthenticatedRevoked(pairingIdentifier: String, reason: String) {
        InternetProductAdmissionGate.withLock {
            require(reason.isNotBlank()) { "Authenticated revocation reason is required" }
            require(verifiedPairingIdentifier() == pairingIdentifier) { "Authenticated revocation targets another pairing" }
            val pending = loadPendingAuthenticatedRevocation()
            require(pending == null || pending == PendingAuthenticatedRevocation(pairingIdentifier, reason)) {
                "Authenticated revocation completion does not match the durable pending record"
            }
            check(
                preferences
                    .edit()
                    .putString(REVOKED_PAIRING_KEY, pairingIdentifier)
                    .remove(PENDING_AUTHENTICATED_REVOCATION_KEY)
                    .commit(),
            ) { "Failed to persist the authenticated revocation tombstone" }
        }
    }

    fun retryPendingAuthenticatedRevocation(): Boolean {
        return InternetProductAdmissionGate.withLock {
            val pending = loadPendingAuthenticatedRevocation() ?: return@withLock false
            markAuthenticatedRevoked(pending.pairingIdentifier, pending.reason)
            true
        }
    }

    fun isRevoked(pairingIdentifier: String): Boolean =
        InternetProductAdmissionGate.withLock {
            preferences.getString(REVOKED_PAIRING_KEY, null) == pairingIdentifier ||
                loadPendingAuthenticatedRevocation()?.pairingIdentifier == pairingIdentifier
        }

    fun hasDurableCredentialMutationBlock(targetPairingIdentifier: String?): Boolean =
        InternetProductAdmissionGate.withLock {
            val verifiedPairingIdentifier = loadPairingRecord()?.pairingIdentifier
            val profilePairingIdentifier = loadPublicProfile()?.pairingIdentifier
            InternetCredentialOwnershipPolicy.blocksMutation(
                targetPairingIdentifier = targetPairingIdentifier,
                verifiedPairingIdentifier = verifiedPairingIdentifier,
                profilePairingIdentifier = profilePairingIdentifier,
                revokedPairingIdentifier = preferences.getString(REVOKED_PAIRING_KEY, null),
                hasPendingAuthenticatedRevocation = loadPendingAuthenticatedRevocation() != null,
                hasPendingRevocationCleanup = loadPendingRevocationCleanup() != null,
            )
        }

    fun loadPublicProfile(): StoredInternetSessionProfile? =
        preferences.getString(PROFILE_KEY, null)?.let { InternetSessionProfileCodec.decodePublic(it, debuggable) }

    fun exportNonSecretSummary(): String? =
        loadPublicProfile()?.let {
            "${it.signalingUrl} · ${it.signalingSessionId} · epoch ${it.authoritativeSessionEpoch}"
        }

    @SuppressLint("ApplySharedPref") // Revocation must be durably recorded before returning to the UI.
    fun remove(pairingIdentifier: String) {
        val profile = loadPublicProfile()
        require(profile == null || profile.pairingIdentifier == pairingIdentifier) { "Pairing identifier does not match active profile" }
        val secretName = profile?.let(::profileSecretName)
        val cleanupQueue = secretName?.let { enqueueDeferredSecretCleanup(loadDeferredSecretCleanup(), it) }
            ?: loadDeferredSecretCleanup()
        check(
            commitProfileRemoval(cleanupQueue) { queued ->
                val editor = preferences.edit().remove(PROFILE_KEY)
                if (queued.isEmpty()) editor.remove(DEFERRED_SECRET_CLEANUP_KEY) else {
                    editor.putStringSet(DEFERRED_SECRET_CLEANUP_KEY, queued)
                }
                editor.commit()
            },
        ) { "Failed to durably schedule Internet session credential deletion" }
        inMemoryDeferredCleanup.replaceAfterDurableCommit(cleanupQueue)
        retryDeferredCredentialCleanup()
    }

    @SuppressLint("ApplySharedPref")
    fun removePairingBinding() {
        check(preferences.edit().remove(PAIRING_KEY).commit()) { "Failed to delete verified pairing metadata" }
    }

    internal fun removePairingBindingIfMatches(
        permit: InternetProductCredentialMutationPermit,
        pairingIdentifier: String,
    ) {
        permit.requireActive()
        val current = loadPairingRecord() ?: return
        if (current.pairingIdentifier != pairingIdentifier) return
        removePairingBinding()
    }

    @SuppressLint("ApplySharedPref")
    fun beginRevocationCleanup(
        pairingIdentifier: String,
        localDeviceId: String,
        identityEpoch: Long,
    ) {
        InternetProductAdmissionGate.withLock {
            val requested = PendingRevocationCleanup(pairingIdentifier, localDeviceId, identityEpoch)
            val existing = loadPendingRevocationCleanup()
            require(
                existing == null ||
                    existing.pairingIdentifier == pairingIdentifier &&
                    existing.localDeviceId == localDeviceId &&
                    existing.identityEpoch == identityEpoch,
            ) { "Another revocation cleanup is already pending" }
            if (existing != null) return@withLock
            check(
                preferences
                    .edit()
                    .putString(REVOKED_PAIRING_KEY, pairingIdentifier)
                    .putString(PENDING_REVOCATION_CLEANUP_KEY, PendingRevocationCleanupCodec.encode(requested))
                    .commit(),
            ) { "Failed to persist revocation cleanup intent" }
        }
    }

    internal fun retryPendingRevocationCleanup(
        deletePairingSecret: (String) -> Unit,
        deleteIdentityKey: (String, Long) -> Unit,
    ): RevocationCleanupResult? {
        return InternetProductAdmissionGate.withLock {
            val pending = loadPendingRevocationCleanup() ?: return@withLock null
            retryOwnedRevocationCleanup(
                initial = pending,
                currentProfilePairingIdentifier = { loadPublicProfile()?.pairingIdentifier },
                currentBindingPairingIdentifier = { loadPairingRecord()?.pairingIdentifier },
                deletePairingSecret = deletePairingSecret,
                deleteIdentityKey = deleteIdentityKey,
                deleteSessionCredentials = ::remove,
                deletePairingMetadata = { _ -> removePairingBinding() },
                persist = ::persistPendingRevocationCleanup,
            )
        }
    }

    internal fun loadPendingRevocationCleanup(): PendingRevocationCleanup? =
        preferences
            .getString(PENDING_REVOCATION_CLEANUP_KEY, null)
            ?.let(PendingRevocationCleanupCodec::decode)

    private fun loadPendingAuthenticatedRevocation(): PendingAuthenticatedRevocation? =
        preferences
            .getString(PENDING_AUTHENTICATED_REVOCATION_KEY, null)
            ?.let(::decodePendingAuthenticatedRevocation)

    private fun encodePendingAuthenticatedRevocation(pending: PendingAuthenticatedRevocation): String =
        JsonObject().apply {
            addProperty("version", 1)
            addProperty("pairing_id", pending.pairingIdentifier)
            addProperty("reason", pending.reason)
        }.toString()

    private fun decodePendingAuthenticatedRevocation(value: String): PendingAuthenticatedRevocation {
        val root = JsonParser.parseString(value).asJsonObject
        require(root.keySet() == PENDING_AUTHENTICATED_REVOCATION_KEYS && root.get("version")?.asInt == 1) {
            "Stored pending authenticated revocation is malformed"
        }
        return PendingAuthenticatedRevocation(
            pairingIdentifier = root.get("pairing_id").asString.also { require(it.isNotBlank()) },
            reason = root.get("reason").asString.also { require(it.isNotBlank()) },
        )
    }

    @SuppressLint("ApplySharedPref")
    private fun persistPendingRevocationCleanup(pending: PendingRevocationCleanup?): Boolean {
        val editor = preferences.edit()
        if (pending == null) editor.remove(PENDING_REVOCATION_CLEANUP_KEY) else {
            editor.putString(PENDING_REVOCATION_CLEANUP_KEY, PendingRevocationCleanupCodec.encode(pending))
        }
        return editor.commit()
    }

    internal fun profileSecretName(profile: StoredInternetSessionProfile): String =
        "$SECRET_PREFIX.${MessageDigest.getInstance("SHA-256").digest("${profile.pairingIdentifier}\u0000${profile.signalingSessionId}\u0000${profile.authoritativeSessionEpoch}".toByteArray()).toHex()}"

    @SuppressLint("ApplySharedPref")
    private fun retryDeferredCredentialCleanup() {
        val pending = loadDeferredSecretCleanup()
        if (pending.isEmpty()) return
        val deleted = mutableSetOf<String>()
        pending.forEach { secretName ->
            try {
                secretStore.delete(secretName)
                deleted += secretName
            } catch (_: Throwable) {
                // Retain this opaque slot name for the next import/connect retry.
            }
        }
        val remaining = pending - deleted
        val editor = preferences.edit()
        if (remaining.isEmpty()) editor.remove(DEFERRED_SECRET_CLEANUP_KEY) else editor.putStringSet(DEFERRED_SECRET_CLEANUP_KEY, remaining)
        if (editor.commit()) {
            inMemoryDeferredCleanup.replaceAfterDurableCommit(remaining)
        } else {
            // Keep the original set in memory so this process retries even when
            // SharedPreferences persistence is temporarily unavailable.
            inMemoryDeferredCleanup.merge(pending)
            android.util.Log.e(TAG, "Could not persist deferred Internet credential cleanup progress")
        }
    }

    private fun loadDeferredSecretCleanup(): Set<String> {
        val persisted = try {
            preferences.getStringSet(DEFERRED_SECRET_CLEANUP_KEY, emptySet()).orEmpty().toSet()
        } catch (_: ClassCastException) {
            // One-time migration from the original single-slot preference.
            preferences.getString(DEFERRED_SECRET_CLEANUP_KEY, null)?.let(::setOf).orEmpty()
        }
        inMemoryDeferredCleanup.merge(persisted)
        return inMemoryDeferredCleanup.snapshot()
    }

    private fun loadVerifiedPairingBinding(): StoredPairingBinding? =
        when (val record = loadPairingRecord()) {
            null -> null
            is StoredPairingBinding -> record
            is LegacyStoredPairingBinding -> throw IllegalStateException(LEGACY_PAIRING_REPAIR_MESSAGE)
        }

    private fun loadPairingRecord(): StoredPairingRecord? {
        val root = preferences.getString(PAIRING_KEY, null)?.let { JsonParser.parseString(it).asJsonObject } ?: return null
        return when (root.keySet()) {
            PAIRING_V2_KEYS -> {
                require(root.bindingVersion() == PAIRING_VERSION) { "Stored pairing metadata version is unsupported" }
                StoredPairingBinding(
                    pairingIdentifier = root.bindingString("pairing_id"),
                    hostIdentity = root.bindingIdentity("host"),
                    localIdentity = root.bindingIdentity("local"),
                    sessionContext = root.bindingContext(),
                )
            }

            LEGACY_PAIRING_V1_KEYS ->
                LegacyStoredPairingBinding(
                    pairingIdentifier = root.bindingString("pairing_id"),
                    hostIdentity = root.bindingIdentity("host"),
                    localDeviceId = root.bindingString("local_device_id"),
                    localIdentityEpoch = root.bindingPositiveLong("local_identity_epoch"),
                    sessionContext = root.bindingContext(),
                )

            else -> throw IllegalArgumentException("Stored pairing metadata is malformed")
        }
    }

    private fun JsonObject.bindingIdentity(prefix: String): InternetPairingIdentity =
        InternetPairingIdentity(
            deviceId = bindingString("${prefix}_device_id"),
            keyId = bindingString("${prefix}_key_id"),
            keyEpoch = bindingPositiveLong("${prefix}_identity_epoch"),
            signatureAlgorithm = bindingString("${prefix}_signature_algorithm"),
            signingPublicKey = Base64.getDecoder().decode(bindingString("${prefix}_signing_public_key")),
        )

    private fun JsonObject.bindingVersion(): Int {
        val literal = get("version")?.takeIf { it.isJsonPrimitive && it.asJsonPrimitive.isNumber }?.toString()
            ?: throw IllegalArgumentException("Stored pairing metadata version is invalid")
        require(literal.matches(Regex("[0-9]+"))) { "Stored pairing metadata version is invalid" }
        return literal.toIntOrNull() ?: throw IllegalArgumentException("Stored pairing metadata version is invalid")
    }

    private fun JsonObject.bindingString(name: String): String =
        get(name)?.takeIf { it.isJsonPrimitive && it.asJsonPrimitive.isString }?.asString
            ?.also { require(it.isNotBlank() && it.toByteArray().size <= 256) { "Stored pairing field is invalid" } }
            ?: throw IllegalArgumentException("Stored pairing field is invalid")

    private fun JsonObject.bindingPositiveLong(name: String): Long {
        val literal = get(name)?.takeIf { it.isJsonPrimitive && it.asJsonPrimitive.isNumber }?.toString()
            ?: throw IllegalArgumentException("Stored pairing epoch is invalid")
        require(literal.matches(Regex("[0-9]+"))) { "Stored pairing epoch is invalid" }
        return (literal.toLongOrNull() ?: throw IllegalArgumentException("Stored pairing epoch is invalid"))
            .also { require(it in 1 until Long.MAX_VALUE) { "Stored pairing epoch is invalid" } }
    }

    private fun JsonObject.bindingContext(): ByteArray =
        Base64.getDecoder().decode(bindingString("session_context")).also {
            require(it.size == 32) { "Stored pairing context is invalid" }
        }

    private fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it) }

    companion object {
        private const val PREFERENCES_NAME = "phase3_internet_profile"
        internal const val PROFILE_KEY = "active_profile"
        internal const val PAIRING_KEY = "verified_pairing"
        private const val REVOKED_PAIRING_KEY = "revoked_pairing"
        private const val PENDING_AUTHENTICATED_REVOCATION_KEY = "pending_authenticated_revocation"
        internal const val DEFERRED_SECRET_CLEANUP_KEY = "deferred_secret_cleanup"
        internal const val PENDING_REVOCATION_CLEANUP_KEY = "pending_revocation_cleanup"
        private const val SECRET_PREFIX = "phase3.internet.profile.v1"
        private const val FINGERPRINT_CHARACTERS = 16
        private const val TAG = "InternetProfileStore"
        private const val PAIRING_VERSION = 2
        private const val LEGACY_PAIRING_REPAIR_MESSAGE =
            "Stored pairing metadata predates local identity binding; pair again"
        private val LEGACY_PAIRING_V1_KEYS =
            setOf(
                "pairing_id", "host_device_id", "host_key_id", "host_identity_epoch",
                "host_signature_algorithm", "host_signing_public_key",
                "local_device_id", "local_identity_epoch", "session_context",
            )
        private val PAIRING_V2_KEYS =
            LEGACY_PAIRING_V1_KEYS +
                setOf(
                    "version", "local_key_id", "local_signature_algorithm", "local_signing_public_key",
                )
        private val PENDING_AUTHENTICATED_REVOCATION_KEYS = setOf("version", "pairing_id", "reason")
    }
}

internal fun enqueueDeferredSecretCleanup(existing: Set<String>, secretName: String): Set<String> {
    require(secretName.isNotBlank()) { "Deferred secret name is required" }
    return existing + secretName
}

internal fun commitProfileRemoval(
    cleanupQueue: Set<String>,
    commitPointerAndCleanup: (Set<String>) -> Boolean,
): Boolean = commitPointerAndCleanup(cleanupQueue)

internal fun commitProfileReplacement(
    cleanupQueue: Set<String>,
    commitPointerAndCleanup: (Set<String>) -> Boolean,
    rollbackNewSecret: () -> Unit,
): Boolean {
    if (commitPointerAndCleanup(cleanupQueue)) return true
    rollbackNewSecret()
    return false
}

internal object InternetSessionLeaseSignature {
    private const val DOMAIN = "vibescreen/internet-session-lease/v1"
    private const val VERSION = 1L

    fun digest(decoded: DecodedInternetProfile): ByteArray =
        digest(decoded.profile, decoded.secrets)

    fun digest(
        profile: StoredInternetSessionProfile,
        secrets: ImportedInternetSecrets,
    ): ByteArray = digest(profile, secrets, SensitiveBufferObserver.NONE)

    internal fun digest(
        profile: StoredInternetSessionProfile,
        secrets: ImportedInternetSecrets,
        observer: SensitiveBufferObserver,
    ): ByteArray {
        require(profile.iceServerUrls.size == secrets.turnCredentials.size) {
            "Stored ICE credentials do not match the lease"
        }
        return SecurityTranscript.digest(DOMAIN, observer) {
            uint64(VERSION)
            text(profile.pairingIdentifier)
            text(profile.pinnedHostId)
            text(profile.leaseHostKeyId)
            text(profile.pinnedDeviceId)
            text(profile.leaseDeviceKeyId)
            text(profile.signalingUrl)
            text(profile.signalingSessionId)
            uint64(profile.authoritativeSessionEpoch)
            uint64(profile.hostIdentityEpoch)
            uint64(profile.deviceIdentityEpoch)
            uint64(profile.expiresAtUnixSeconds)
            part(profile.transcriptContext)
            part(profile.protocolSessionId)
            secrets.signalingToken.withBytes(::part)
            uint64(profile.iceServerUrls.size.toLong())
            profile.iceServerUrls.forEachIndexed { index, urls ->
                uint64(urls.size.toLong())
                urls.forEach(::text)
                val credentials = secrets.turnCredentials[index]
                nullableSecret(credentials.first)
                nullableSecret(credentials.second)
            }
            byte(if (profile.allowInsecureForTesting) 1.toByte() else 0.toByte())
        }
    }

    fun verify(
        decoded: DecodedInternetProfile,
        hostIdentity: InternetPairingIdentity,
    ) {
        require(decoded.profile.pinnedHostId == hostIdentity.deviceId) {
            "Lease host identity does not match the verified Mac"
        }
        require(decoded.profile.leaseHostKeyId == hostIdentity.keyId) {
            "Lease signing key does not match the verified Mac"
        }
        require(decoded.profile.hostIdentityEpoch == hostIdentity.keyEpoch) {
            "Lease host identity epoch does not match the verified Mac"
        }
        require(verify(hostIdentity.signingPublicKey, digest(decoded), decoded.profile.leaseSignature)) {
            "Internet session lease signature is invalid"
        }
    }

    private fun TranscriptDigestUpdater.nullableSecret(value: DestroyableUtf8?) {
        byte(if (value == null) 0.toByte() else 1.toByte())
        value?.withBytes(::part)
    }
}

private fun verifySignedLease(
    decoded: DecodedInternetProfile,
    pairing: StoredPairingBinding,
) = InternetSessionLeaseSignature.verify(decoded, pairing.hostIdentity)

internal object InternetSessionProfileCodec {
    private val ROOT_KEYS =
        setOf(
            "version",
            "pairing_id",
            "pinned_host_id",
            "pinned_device_id",
            "lease_device_key_id",
            "signaling_url",
            "signaling_session_id",
            "session_epoch",
            "host_identity_epoch",
            "device_identity_epoch",
            "expires_at",
            "transcript_context",
            "protocol_session_id",
            "signaling_token",
            "ice_servers",
            "allow_insecure_for_testing",
            "lease_host_key_id",
            "lease_signature",
        )
    private val ICE_KEYS = setOf("urls", "username", "credential")
    private val PUBLIC_KEYS = ROOT_KEYS - setOf("signaling_token")
    private val SECRET_KEYS = setOf("signaling_token", "turn_credentials")

    fun decode(json: String, debuggable: Boolean): DecodedInternetProfile {
        require(json.utf8LengthAtMost(MAX_PROFILE_BYTES)) { "Internet profile is too large" }
        return decodeProfile(JsonReader(StringReader(json)), debuggable)
    }

    fun encodePublic(profile: StoredInternetSessionProfile): String =
        JsonObject().apply {
            addProperty("version", VERSION)
            addProperty("pairing_id", profile.pairingIdentifier)
            addProperty("pinned_host_id", profile.pinnedHostId)
            addProperty("pinned_device_id", profile.pinnedDeviceId)
            addProperty("lease_device_key_id", profile.leaseDeviceKeyId)
            addProperty("signaling_url", profile.signalingUrl)
            addProperty("signaling_session_id", profile.signalingSessionId)
            addProperty("session_epoch", profile.authoritativeSessionEpoch)
            addProperty("host_identity_epoch", profile.hostIdentityEpoch)
            addProperty("device_identity_epoch", profile.deviceIdentityEpoch)
            addProperty("expires_at", profile.expiresAtUnixSeconds)
            addProperty("transcript_context", profile.transcriptContext.base64())
            addProperty("protocol_session_id", profile.protocolSessionId.base64())
            add("ice_servers", JsonArray().apply { profile.iceServerUrls.forEach { server -> add(JsonObject().apply { add("urls", server.toJsonArray()); add("username", null); add("credential", null) }) } })
            addProperty("allow_insecure_for_testing", profile.allowInsecureForTesting)
            addProperty("lease_host_key_id", profile.leaseHostKeyId)
            addProperty("lease_signature", profile.leaseSignature.base64())
        }.toString()

    fun decodePublic(json: String, debuggable: Boolean): StoredInternetSessionProfile {
        val root = JsonParser.parseString(json).asJsonObject
        require(root.keySet() == PUBLIC_KEYS) { "Stored Internet profile is malformed" }
        val synthetic = root.deepCopy().apply {
            addProperty("signaling_token", "x".repeat(MIN_SIGNALING_TOKEN_BYTES))
            requiredArray("ice_servers").forEach { element ->
                val server = element.asJsonObject
                if (server.requiredArray("urls").any { it.asString.startsWith("turn:") || it.asString.startsWith("turns:") }) {
                    server.addProperty("username", "stored")
                    server.addProperty("credential", "stored")
                }
            }
        }
        return decode(synthetic.toString(), debuggable).also { it.close() }.profile
    }

    fun encodeSecrets(secrets: ImportedInternetSecrets): ByteArray {
        val output = ZeroizableByteArrayOutputStream(MAX_PROFILE_BYTES)
        val writer = JsonWriter(OutputStreamWriter(output, Charsets.UTF_8))
        try {
            writer.beginObject()
            writer.name("signaling_token")
            secrets.signalingToken.withString(writer::value)
            writer.name("turn_credentials").beginArray()
            secrets.turnCredentials.forEach { (username, credential) ->
                writer.beginObject()
                writer.name("username")
                if (username == null) writer.nullValue() else username.withString(writer::value)
                writer.name("credential")
                if (credential == null) writer.nullValue() else credential.withString(writer::value)
                writer.endObject()
            }
            writer.endArray().endObject()
            writer.flush()
            return output.toByteArray()
        } finally {
            runCatching { writer.close() }
            output.destroy()
        }
    }

    fun decodeSecrets(json: ByteArray, expectedIceServers: Int): ImportedInternetSecrets {
        require(json.size <= MAX_PROFILE_BYTES) { "Stored Internet credentials are too large" }
        // JsonReader is bounded and streaming, so no whole plaintext JSON String is created.
        // Its internal parser buffers, like Android/OkHttp/libwebrtc String copies, are third-party
        // memory that cannot be proven zeroized; all containers owned by this module are erased.
        val reader = JsonReader(InputStreamReader(ByteArrayInputStream(json), Charsets.UTF_8))
        var token: DestroyableUtf8? = null
        val credentials = mutableListOf<Pair<DestroyableUtf8?, DestroyableUtf8?>>()
        val keys = mutableSetOf<String>()
        try {
            reader.beginObject()
            while (reader.hasNext()) {
                when (val name = reader.nextName()) {
                    "signaling_token" -> {
                        require(keys.add(name)) { "Stored Internet credentials contain duplicate fields" }
                        token = reader.nextSecret(MAX_TOKEN_BYTES, "signaling_token")
                    }
                    "turn_credentials" -> {
                        require(keys.add(name)) { "Stored Internet credentials contain duplicate fields" }
                        reader.beginArray()
                        while (reader.hasNext()) credentials += reader.readCredentialPair()
                        reader.endArray()
                    }
                    else -> throw IllegalArgumentException("Stored Internet credentials contain unknown field: $name")
                }
            }
            reader.endObject()
            require(keys == SECRET_KEYS && credentials.size == expectedIceServers) { "Stored Internet credentials are malformed" }
            return ImportedInternetSecrets(requireNotNull(token), credentials.toList()).also { token = null; credentials.clear() }
        } catch (failure: Throwable) {
            token?.close()
            credentials.forEach { (username, credential) -> username?.close(); credential?.close() }
            throw failure
        }
    }

    private fun decodeProfile(reader: JsonReader, debuggable: Boolean): DecodedInternetProfile {
        val fields = mutableMapOf<String, Any>()
        var signalingToken: DestroyableUtf8? = null
        val iceUrls = mutableListOf<List<String>>()
        val credentials = mutableListOf<Pair<DestroyableUtf8?, DestroyableUtf8?>>()
        try {
            reader.beginObject()
            while (reader.hasNext()) {
                val name = reader.nextName()
                require(name in ROOT_KEYS && name !in fields) { "Internet profile contains duplicate or unknown field: $name" }
                when (name) {
                    "version" -> fields[name] = reader.nextStrictInteger(name).toIntOrNull() ?: throw IllegalArgumentException("$name is outside the integer range")
                    "session_epoch", "host_identity_epoch", "device_identity_epoch", "expires_at" ->
                        fields[name] = reader.nextStrictInteger(name).toLongOrNull() ?: throw IllegalArgumentException("$name is outside the integer range")
                    "allow_insecure_for_testing" -> fields[name] = reader.nextBoolean()
                    "signaling_token" -> {
                        signalingToken = reader.nextSecret(MAX_TOKEN_BYTES, name)
                        fields[name] = true
                    }
                    "ice_servers" -> {
                        reader.beginArray()
                        while (reader.hasNext()) {
                            require(iceUrls.size < MAX_ICE_SERVERS) { "ICE server count is invalid" }
                            val (urls, credential) = reader.readIceServer()
                            iceUrls += urls
                            credentials += credential
                        }
                        reader.endArray()
                        fields[name] = true
                    }
                    else -> fields[name] = reader.nextBoundedString(maximumBytesFor(name), name)
                }
            }
            reader.endObject()
            require(fields.keys == ROOT_KEYS) { "Internet profile contains missing or unknown fields" }
            require(fields.getValue("version") == VERSION) { "Unsupported Internet profile version" }
            require(iceUrls.isNotEmpty()) { "ICE server count is invalid" }
            val token = requireNotNull(signalingToken)
            require(token.byteLength() >= MIN_SIGNALING_TOKEN_BYTES) { "Signaling token is invalid" }
            val signalingUrl = fields.string("signaling_url")
            val allowInsecure = fields.getValue("allow_insecure_for_testing") as Boolean
            validateSignalingUrl(signalingUrl, allowInsecure, debuggable)
            fun positiveLong(name: String): Long =
                (fields.getValue(name) as Long).also { require(it in 1 until Long.MAX_VALUE) { "$name must be positive and below the reserved maximum" } }
            val profile =
                StoredInternetSessionProfile(
                    pairingIdentifier = fields.string("pairing_id"),
                    pinnedHostId = fields.string("pinned_host_id"),
                    pinnedDeviceId = fields.string("pinned_device_id"),
                    leaseDeviceKeyId = fields.string("lease_device_key_id"),
                    signalingUrl = signalingUrl,
                    signalingSessionId = fields.string("signaling_session_id"),
                    authoritativeSessionEpoch = positiveLong("session_epoch"),
                    hostIdentityEpoch = positiveLong("host_identity_epoch"),
                    deviceIdentityEpoch = positiveLong("device_identity_epoch"),
                    expiresAtUnixSeconds = positiveLong("expires_at"),
                    transcriptContext = fields.base64("transcript_context", TRANSCRIPT_BYTES..TRANSCRIPT_BYTES),
                    protocolSessionId = fields.base64("protocol_session_id", 1..MAX_IDENTIFIER_BYTES),
                    iceServerUrls = iceUrls.toList(),
                    allowInsecureForTesting = allowInsecure,
                    leaseHostKeyId = fields.string("lease_host_key_id"),
                    leaseSignature = fields.base64("lease_signature", 1..MAX_SIGNATURE_BYTES),
                )
            return DecodedInternetProfile(profile, ImportedInternetSecrets(token, credentials.toList())).also {
                signalingToken = null
                credentials.clear()
            }
        } catch (failure: Throwable) {
            signalingToken?.close()
            credentials.forEach { (username, credential) -> username?.close(); credential?.close() }
            throw failure
        }
    }

    private fun JsonReader.readIceServer(): Pair<List<String>, Pair<DestroyableUtf8?, DestroyableUtf8?>> {
        val keys = mutableSetOf<String>()
        val urls = mutableListOf<String>()
        var username: DestroyableUtf8? = null
        var credential: DestroyableUtf8? = null
        try {
            beginObject()
            while (hasNext()) {
                when (val name = nextName()) {
                    "urls" -> {
                        require(keys.add(name)) { "ICE server contains duplicate fields" }
                        beginArray()
                        while (hasNext()) {
                            require(urls.size < MAX_ICE_URLS) { "ICE URL count is invalid" }
                            urls += nextBoundedString(MAX_URL_BYTES, "ICE URL")
                        }
                        endArray()
                    }
                    "username" -> {
                        require(keys.add(name)) { "ICE server contains duplicate fields" }
                        username = nextNullableSecret(MAX_CREDENTIAL_BYTES, name)
                    }
                    "credential" -> {
                        require(keys.add(name)) { "ICE server contains duplicate fields" }
                        credential = nextNullableSecret(MAX_CREDENTIAL_BYTES, name)
                    }
                    else -> throw IllegalArgumentException("ICE server contains unknown field: $name")
                }
            }
            endObject()
            require(keys == ICE_KEYS && urls.isNotEmpty()) { "ICE server contains missing fields" }
            require(urls.all { it.startsWith("stun:") || it.startsWith("stuns:") || it.startsWith("turn:") || it.startsWith("turns:") }) {
                "ICE URLs must use stun, stuns, turn, or turns"
            }
            if (urls.any { it.startsWith("turn:") || it.startsWith("turns:") }) {
                require(username != null && !username.isBlank() && credential != null && !credential.isBlank()) {
                    "TURN servers require username and credential"
                }
            }
            return urls.toList() to (username to credential).also { username = null; credential = null }
        } catch (failure: Throwable) {
            username?.close()
            credential?.close()
            throw failure
        }
    }

    private fun JsonReader.readCredentialPair(): Pair<DestroyableUtf8?, DestroyableUtf8?> {
        val keys = mutableSetOf<String>()
        var username: DestroyableUtf8? = null
        var credential: DestroyableUtf8? = null
        try {
            beginObject()
            while (hasNext()) {
                when (val name = nextName()) {
                    "username" -> { require(keys.add(name)); username = nextNullableSecret(MAX_CREDENTIAL_BYTES, name) }
                    "credential" -> { require(keys.add(name)); credential = nextNullableSecret(MAX_CREDENTIAL_BYTES, name) }
                    else -> throw IllegalArgumentException("Stored TURN credential contains unknown field: $name")
                }
            }
            endObject()
            require(keys == setOf("username", "credential")) { "Stored TURN credential is malformed" }
            return (username to credential).also { username = null; credential = null }
        } catch (failure: Throwable) {
            username?.close()
            credential?.close()
            throw failure
        }
    }

    private fun JsonReader.nextNullableSecret(maxBytes: Int, name: String): DestroyableUtf8? =
        if (peek() == JsonToken.NULL) { nextNull(); null } else nextSecret(maxBytes, name)

    private fun JsonReader.nextSecret(maxBytes: Int, name: String): DestroyableUtf8 {
        val transient = nextBoundedString(maxBytes, name)
        return DestroyableUtf8.fromString(transient)
    }

    private fun JsonReader.nextBoundedString(maxBytes: Int, name: String): String {
        require(peek() == JsonToken.STRING) { "$name must be a string" }
        return nextString().also { require(it.isNotBlank() && it.utf8LengthAtMost(maxBytes)) { "$name is invalid" } }
    }

    private fun JsonReader.nextStrictInteger(name: String): String {
        require(peek() == JsonToken.NUMBER) { "$name must be an integer" }
        return nextString().also { require(it.matches(Regex("-?[0-9]+"))) { "$name must be an integer" } }
    }

    private fun maximumBytesFor(name: String): Int =
        when (name) {
            "signaling_url" -> MAX_URL_BYTES
            "transcript_context", "protocol_session_id", "lease_signature" -> MAX_BASE64_BYTES
            else -> MAX_IDENTIFIER_BYTES
        }

    private fun Map<String, Any>.string(name: String): String = getValue(name) as String

    private fun Map<String, Any>.base64(name: String, size: IntRange): ByteArray =
        try {
            Base64.getDecoder().decode(string(name)).also { require(it.size in size) { "$name decoded length is invalid" } }
        } catch (failure: IllegalArgumentException) {
            throw IllegalArgumentException("$name is invalid base64", failure)
        }

    private fun validateSignalingUrl(url: String, allowInsecure: Boolean, debuggable: Boolean) {
        val uri = URI(url)
        if (allowInsecure) {
            require(debuggable && uri.scheme == "http" && uri.host in LOOPBACK_HOSTS) {
                "Insecure signaling is limited to loopback debug builds"
            }
        } else {
            require(uri.scheme == "https") { "Production signaling requires HTTPS" }
        }
        require(uri.rawQuery == null && uri.rawFragment == null && uri.userInfo == null && !uri.host.isNullOrBlank()) {
            "Signaling URL is invalid"
        }
    }

    private fun JsonObject.requiredString(name: String, maxBytes: Int): String {
        val value =
            get(name)?.takeIf { it.isJsonPrimitive && it.asJsonPrimitive.isString }?.asString
                ?: throw IllegalArgumentException("$name must be a string")
        require(value.isNotBlank() && value.toByteArray().size <= maxBytes) { "$name is invalid" }
        return value
    }

    private fun JsonObject.nullableString(name: String, maxBytes: Int): String? =
        get(name)?.takeUnless { it.isJsonNull }?.also {
            require(it.isJsonPrimitive && it.asJsonPrimitive.isString) { "$name must be a string or null" }
        }?.asString?.also {
            require(it.isNotBlank() && it.toByteArray().size <= maxBytes) { "$name is invalid" }
        }

    private fun JsonObject.requiredInt(name: String): Int =
        requiredIntegerLiteral(name).toIntOrNull() ?: throw IllegalArgumentException("$name is outside the integer range")
    private fun JsonObject.requiredPositiveLong(name: String): Long =
        (requiredIntegerLiteral(name).toLongOrNull() ?: throw IllegalArgumentException("$name is outside the integer range"))
            .also { require(it in 1 until Long.MAX_VALUE) { "$name must be positive and below the reserved maximum" } }
    private fun JsonObject.requiredIntegerLiteral(name: String): String {
        val primitive = get(name)?.takeIf { it.isJsonPrimitive && it.asJsonPrimitive.isNumber }?.asJsonPrimitive
            ?: throw IllegalArgumentException("$name must be an integer")
        return primitive.toString().also { require(it.matches(Regex("-?[0-9]+"))) { "$name must be an integer" } }
    }
    private fun JsonObject.requiredBoolean(name: String): Boolean {
        val primitive = get(name)?.takeIf { it.isJsonPrimitive && it.asJsonPrimitive.isBoolean }?.asJsonPrimitive
            ?: throw IllegalArgumentException("$name must be a boolean")
        return primitive.asBoolean
    }
    private fun JsonObject.requiredArray(name: String): JsonArray =
        get(name)?.takeIf { it.isJsonArray }?.asJsonArray ?: throw IllegalArgumentException("$name must be an array")
    private fun JsonObject.requiredBase64(name: String, size: IntRange): ByteArray =
        try {
            Base64.getDecoder().decode(requiredString(name, MAX_BASE64_BYTES)).also {
                require(it.size in size) { "$name has an invalid size" }
            }
        } catch (failure: IllegalArgumentException) {
            throw IllegalArgumentException("$name is not valid base64", failure)
        }

    private fun JsonObject.addNullable(name: String, value: String?) {
        if (value == null) add(name, null) else addProperty(name, value)
    }
    private fun ByteArray.base64(): String = Base64.getEncoder().encodeToString(this)
    private fun List<String>.toJsonArray() = JsonArray().also { array -> forEach(array::add) }

    private fun String.utf8LengthAtMost(limit: Int): Boolean {
        var bytes = 0
        var index = 0
        while (index < length) {
            val character = this[index]
            bytes +=
                when {
                    character.code <= 0x7f -> 1
                    character.code <= 0x7ff -> 2
                    character.isHighSurrogate() -> {
                        require(index + 1 < length && this[index + 1].isLowSurrogate()) { "Invalid UTF-16 input" }
                        index++
                        4
                    }
                    character.isLowSurrogate() -> throw IllegalArgumentException("Invalid UTF-16 input")
                    else -> 3
                }
            if (bytes > limit) return false
            index++
        }
        return true
    }

    private const val VERSION = 1
    private const val MAX_PROFILE_BYTES = 65_536
    private const val MAX_IDENTIFIER_BYTES = 256
    private const val MAX_URL_BYTES = 2_048
    private const val MAX_TOKEN_BYTES = 8_192
    private const val MIN_SIGNALING_TOKEN_BYTES = 32
    private const val MAX_CREDENTIAL_BYTES = 4_096
    private const val MAX_BASE64_BYTES = 8_192
    private const val MAX_SIGNATURE_BYTES = 512
    private const val MAX_ICE_SERVERS = 16
    private const val MAX_ICE_URLS = 8
    private const val TRANSCRIPT_BYTES = 32
    private val LOOPBACK_HOSTS = setOf("localhost", "127.0.0.1", "::1")
}

internal class ZeroizableByteArrayOutputStream(
    initialCapacity: Int,
) : ByteArrayOutputStream(initialCapacity) {
    @Synchronized
    override fun write(value: Int) {
        val previousBuffer = buf
        try {
            super.write(value)
        } finally {
            zeroRetiredBuffer(previousBuffer)
        }
    }

    @Synchronized
    override fun write(value: ByteArray, offset: Int, length: Int) {
        val previousBuffer = buf
        try {
            super.write(value, offset, length)
        } finally {
            zeroRetiredBuffer(previousBuffer)
        }
    }

    @Synchronized
    fun destroy() {
        buf.fill(0)
        reset()
    }

    @Synchronized
    internal fun backingBufferForTest(): ByteArray = buf

    private fun zeroRetiredBuffer(previousBuffer: ByteArray) {
        if (buf !== previousBuffer) previousBuffer.fill(0)
    }
}
