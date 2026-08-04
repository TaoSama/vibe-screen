package dev.telemachus.display.internet

import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.ApplicationInfo
import com.google.gson.JsonArray
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import dev.telemachus.display.internet.security.AndroidSecretStore
import dev.telemachus.display.internet.security.AndroidStoredInternetSessionFactory
import dev.telemachus.display.internet.security.InternetPairingPublicMetadata
import dev.telemachus.display.internet.security.InternetPairingIdentity
import dev.telemachus.display.internet.security.SecurityTranscript
import dev.telemachus.display.internet.security.verify
import java.net.URI
import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.util.Base64

/** Non-secret, persisted part of a short-lived Internet session lease. */
data class StoredInternetSessionProfile(
    val pairingIdentifier: String,
    val pinnedHostId: String,
    val signalingUrl: String,
    val signalingSessionId: String,
    val authoritativeSessionEpoch: Long,
    val identityEpoch: Long,
    val transcriptContext: ByteArray,
    val protocolSessionId: ByteArray,
    val iceServerUrls: List<List<String>>,
    val allowInsecureForTesting: Boolean,
    val leaseHostKeyId: String,
    val leaseSignature: ByteArray,
)

internal data class ImportedInternetSecrets(
    val signalingToken: String,
    val turnCredentials: List<Pair<String?, String?>>,
)

internal data class DecodedInternetProfile(
    val profile: StoredInternetSessionProfile,
    val secrets: ImportedInternetSecrets,
) : AutoCloseable {
    override fun close() = Unit
}

private data class StoredPairingBinding(
    val pairingIdentifier: String,
    val hostIdentity: InternetPairingIdentity,
    val localDeviceId: String,
    val localIdentityEpoch: Long,
    val sessionContext: ByteArray,
)

internal class DeferredSecretCleanupPending {
    private val values = mutableSetOf<String>()

    @Synchronized fun merge(incoming: Set<String>) { values += incoming }
    @Synchronized fun enqueue(value: String) { values += value }
    @Synchronized fun replaceAfterDurableCommit(remaining: Set<String>) { values.clear(); values += remaining }
    @Synchronized fun snapshot(): Set<String> = values.toSet()
}

/**
 * Splits imported pairing material into ordinary preferences and AndroidKeyStore-wrapped records.
 * Tokens, TURN credentials, and pairing keys are never returned by [exportNonSecretSummary].
 */
class InternetSessionProfileStore(
    context: Context,
    private val secretStore: AndroidSecretStore = AndroidSecretStore(context.applicationContext),
) {
    private val preferences = context.getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)
    private val debuggable = context.applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE != 0
    private val inMemoryDeferredCleanup = DeferredSecretCleanupPending()

    fun import(
        json: String,
        storedSessionFactory: AndroidStoredInternetSessionFactory,
    ): StoredInternetSessionProfile {
        retryDeferredCredentialCleanup()
        val decoded = InternetSessionProfileCodec.decode(json, debuggable)
        try {
            val pairing = loadPairingBinding() ?: throw IllegalStateException("Complete signed pairing before importing a lease")
            require(decoded.profile.pairingIdentifier == pairing.pairingIdentifier) { "Lease pairing does not match the verified Mac" }
            require(decoded.profile.pinnedHostId == pairing.hostIdentity.deviceId) { "Lease host identity does not match the verified Mac" }
            require(decoded.profile.identityEpoch == pairing.localIdentityEpoch) { "Lease local identity epoch does not match the paired identity" }
            require(storedSessionFactory.localDeviceId == pairing.localDeviceId) {
                "Lease lifecycle state does not belong to the paired local identity"
            }
            require(decoded.profile.transcriptContext.contentEquals(pairing.sessionContext)) {
                "Lease transcript context does not match signed pairing"
            }
            verifySignedLease(decoded, pairing)
            return storedSessionFactory.withFreshSessionEpochCandidate(decoded.profile.authoritativeSessionEpoch) {
                val current = loadPublicProfile()
                if (current != null) {
                    require(decoded.profile.authoritativeSessionEpoch > current.authoritativeSessionEpoch) {
                        "A replacement Internet lease must use a strictly newer session epoch"
                    }
                }
                val encrypted = InternetSessionProfileCodec.encodeSecrets(decoded.secrets).toByteArray(Charsets.UTF_8)
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
        } finally {
            decoded.close()
        }
    }

    fun loadLease(forceRelay: Boolean): InternetProductSessionLease? {
        retryDeferredCredentialCleanup()
        val profile = loadPublicProfile() ?: return null
        val pairing = loadPairingBinding() ?: return null
        check(profile.pairingIdentifier == pairing.pairingIdentifier && profile.pinnedHostId == pairing.hostIdentity.deviceId) {
            "Stored Internet lease is not bound to the verified pairing"
        }
        check(profile.identityEpoch == pairing.localIdentityEpoch && profile.transcriptContext.contentEquals(pairing.sessionContext)) {
            "Stored Internet lease identity binding is invalid"
        }
        check(!isRevoked(profile.pairingIdentifier)) { "This paired Mac is locally revoked" }
        val encrypted = secretStore.load(profileSecretName(profile)) ?: return null
        val secrets =
            try {
                InternetSessionProfileCodec.decodeSecrets(encrypted.toString(Charsets.UTF_8), profile.iceServerUrls.size)
            } finally {
                encrypted.fill(0)
            }
        try {
            verifySignedLease(DecodedInternetProfile(profile, secrets), pairing)
            val iceServers =
                profile.iceServerUrls.mapIndexed { index, urls ->
                    val credential = secrets.turnCredentials[index]
                    IceServer(urls, credential.first, credential.second)
                }
            return InternetProductSessionLease(
                pairingIdentifier = profile.pairingIdentifier,
                pinnedHostId = profile.pinnedHostId,
                signalingSessionId = profile.signalingSessionId,
                authoritativeSessionEpoch = profile.authoritativeSessionEpoch,
                identityEpoch = profile.identityEpoch,
                transcriptContext = profile.transcriptContext.copyOf(),
                protocolSessionId = profile.protocolSessionId.copyOf(),
                iceServers = iceServers,
                signaling =
                    SignalingConfiguration(
                        baseUrl = profile.signalingUrl,
                        bearerToken = secrets.signalingToken,
                        role = PeerRole.DEVICE,
                        allowInsecureForTesting = profile.allowInsecureForTesting,
                    ),
                iceTransportPolicy = if (forceRelay) IceTransportPolicy.RELAY_ONLY else IceTransportPolicy.ALL,
            )
        } finally {
            Unit
        }
    }

    @SuppressLint("ApplySharedPref")
    fun recordVerifiedPairing(
        metadata: InternetPairingPublicMetadata,
        storedSessionFactory: AndroidStoredInternetSessionFactory,
    ) {
        require(!isRevoked(metadata.pairingIdentifier)) { "This Mac pairing is locally revoked" }
        val context = requireNotNull(metadata.sessionContext) { "Completed pairing must include a session context" }
        val value =
            JsonObject().apply {
                addProperty("pairing_id", metadata.pairingIdentifier)
                addProperty("host_device_id", metadata.hostIdentity.deviceId)
                addProperty("host_key_id", metadata.hostIdentity.keyId)
                addProperty("host_identity_epoch", metadata.hostIdentity.keyEpoch)
                addProperty("host_signature_algorithm", metadata.hostIdentity.signatureAlgorithm)
                addProperty("host_signing_public_key", Base64.getEncoder().encodeToString(metadata.hostIdentity.signingPublicKey))
                addProperty("local_device_id", metadata.deviceIdentity.deviceId)
                addProperty("local_identity_epoch", metadata.deviceIdentity.keyEpoch)
                addProperty("session_context", Base64.getEncoder().encodeToString(context))
            }.toString()
        storedSessionFactory.authorizeIdentityEpoch(metadata.deviceIdentity.keyEpoch)
        check(preferences.edit().putString(PAIRING_KEY, value).commit()) { "Failed to persist verified pairing metadata" }
    }

    fun hasVerifiedPairing(): Boolean = loadPairingBinding() != null

    fun verifiedPairingIdentifier(): String? = loadPairingBinding()?.pairingIdentifier

    fun verifiedLocalIdentityEpoch(): Long? = loadPairingBinding()?.localIdentityEpoch

    fun verifiedHostKeyFingerprint(): String? = loadPairingBinding()?.hostIdentity?.keyId?.take(FINGERPRINT_CHARACTERS)

    @SuppressLint("ApplySharedPref")
    fun markRevoked(pairingIdentifier: String) {
        check(preferences.edit().putString(REVOKED_PAIRING_KEY, pairingIdentifier).commit()) {
            "Failed to persist the local revocation tombstone"
        }
    }

    fun markAuthenticatedRevoked(pairingIdentifier: String, reason: String) {
        require(reason.isNotBlank()) { "Authenticated revocation reason is required" }
        require(verifiedPairingIdentifier() == pairingIdentifier) { "Authenticated revocation targets another pairing" }
        markRevoked(pairingIdentifier)
    }

    fun isRevoked(pairingIdentifier: String): Boolean =
        preferences.getString(REVOKED_PAIRING_KEY, null) == pairingIdentifier

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

    @Synchronized
    @SuppressLint("ApplySharedPref")
    fun beginRevocationCleanup(
        pairingIdentifier: String,
        localDeviceId: String,
        identityEpoch: Long,
    ) {
        val requested = PendingRevocationCleanup(pairingIdentifier, localDeviceId, identityEpoch)
        val existing = loadPendingRevocationCleanup()
        require(
            existing == null ||
                existing.pairingIdentifier == pairingIdentifier &&
                existing.localDeviceId == localDeviceId &&
                existing.identityEpoch == identityEpoch,
        ) { "Another revocation cleanup is already pending" }
        if (existing != null) return
        check(
            preferences
                .edit()
                .putString(REVOKED_PAIRING_KEY, pairingIdentifier)
                .putString(PENDING_REVOCATION_CLEANUP_KEY, PendingRevocationCleanupCodec.encode(requested))
                .commit(),
        ) { "Failed to persist revocation cleanup intent" }
    }

    @Synchronized
    internal fun retryPendingRevocationCleanup(
        deletePairingSecret: (String) -> Unit,
        deleteIdentityKey: (String, Long) -> Unit,
    ): RevocationCleanupResult? {
        val pending = loadPendingRevocationCleanup() ?: return null
        return retryRevocationCleanup(
            initial = pending,
            execute = { step ->
                when (step) {
                    RevocationCleanupStep.PAIRING_SECRET -> deletePairingSecret(pending.pairingIdentifier)
                    RevocationCleanupStep.IDENTITY_KEY -> deleteIdentityKey(pending.localDeviceId, pending.identityEpoch)
                    RevocationCleanupStep.SESSION_CREDENTIALS -> remove(pending.pairingIdentifier)
                    RevocationCleanupStep.PAIRING_METADATA -> removePairingBinding()
                }
            },
            persist = ::persistPendingRevocationCleanup,
        )
    }

    internal fun loadPendingRevocationCleanup(): PendingRevocationCleanup? =
        preferences
            .getString(PENDING_REVOCATION_CLEANUP_KEY, null)
            ?.let(PendingRevocationCleanupCodec::decode)

    @SuppressLint("ApplySharedPref")
    private fun persistPendingRevocationCleanup(pending: PendingRevocationCleanup?): Boolean {
        val editor = preferences.edit()
        if (pending == null) editor.remove(PENDING_REVOCATION_CLEANUP_KEY) else {
            editor.putString(PENDING_REVOCATION_CLEANUP_KEY, PendingRevocationCleanupCodec.encode(pending))
        }
        return editor.commit()
    }

    private fun profileSecretName(profile: StoredInternetSessionProfile): String =
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

    private fun loadPairingBinding(): StoredPairingBinding? {
        val root = preferences.getString(PAIRING_KEY, null)?.let { JsonParser.parseString(it).asJsonObject } ?: return null
        require(root.keySet() == PAIRING_KEYS) { "Stored pairing metadata is malformed" }
        return StoredPairingBinding(
            root.bindingString("pairing_id"),
            InternetPairingIdentity(
                deviceId = root.bindingString("host_device_id"),
                keyId = root.bindingString("host_key_id"),
                keyEpoch = root.bindingPositiveLong("host_identity_epoch"),
                signatureAlgorithm = root.bindingString("host_signature_algorithm"),
                signingPublicKey = Base64.getDecoder().decode(root.bindingString("host_signing_public_key")),
            ),
            root.bindingString("local_device_id"),
            root.bindingPositiveLong("local_identity_epoch"),
            root.bindingContext(),
        )
    }

    private fun JsonObject.bindingString(name: String): String =
        get(name)?.takeIf { it.isJsonPrimitive && it.asJsonPrimitive.isString }?.asString
            ?.also { require(it.isNotBlank() && it.toByteArray().size <= 256) { "Stored pairing field is invalid" } }
            ?: throw IllegalArgumentException("Stored pairing field is invalid")

    private fun JsonObject.bindingPositiveLong(name: String): Long =
        get(name)?.takeIf { it.isJsonPrimitive && it.asJsonPrimitive.isNumber }?.asLong
            ?.also { require(it in 1 until Long.MAX_VALUE) { "Stored pairing epoch is invalid" } }
            ?: throw IllegalArgumentException("Stored pairing epoch is invalid")

    private fun JsonObject.bindingContext(): ByteArray =
        Base64.getDecoder().decode(bindingString("session_context")).also {
            require(it.size == 32) { "Stored pairing context is invalid" }
        }

    private fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it) }

    companion object {
        private const val PREFERENCES_NAME = "phase3_internet_profile"
        private const val PROFILE_KEY = "active_profile"
        private const val PAIRING_KEY = "verified_pairing"
        private const val REVOKED_PAIRING_KEY = "revoked_pairing"
        private const val DEFERRED_SECRET_CLEANUP_KEY = "deferred_secret_cleanup"
        private const val PENDING_REVOCATION_CLEANUP_KEY = "pending_revocation_cleanup"
        private const val SECRET_PREFIX = "phase3.internet.profile.v1"
        private const val FINGERPRINT_CHARACTERS = 16
        private const val TAG = "InternetProfileStore"
        private val PAIRING_KEYS =
            setOf(
                "pairing_id", "host_device_id", "host_key_id", "host_identity_epoch",
                "host_signature_algorithm", "host_signing_public_key",
                "local_device_id", "local_identity_epoch", "session_context",
            )
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
    ): ByteArray {
        require(profile.iceServerUrls.size == secrets.turnCredentials.size) {
            "Stored ICE credentials do not match the lease"
        }
        val parts = mutableListOf<ByteArray>()
        parts += u64(VERSION)
        parts += text(profile.pairingIdentifier)
        parts += text(profile.pinnedHostId)
        parts += text(profile.leaseHostKeyId)
        parts += text(profile.signalingUrl)
        parts += text(profile.signalingSessionId)
        parts += u64(profile.authoritativeSessionEpoch)
        parts += u64(profile.identityEpoch)
        parts += profile.transcriptContext
        parts += profile.protocolSessionId
        parts += text(secrets.signalingToken)
        parts += u64(profile.iceServerUrls.size.toLong())
        profile.iceServerUrls.forEachIndexed { index, urls ->
            parts += u64(urls.size.toLong())
            urls.forEach { parts += text(it) }
            val credentials = secrets.turnCredentials[index]
            parts.addNullable(credentials.first)
            parts.addNullable(credentials.second)
        }
        parts += byteArrayOf(if (profile.allowInsecureForTesting) 1 else 0)
        return SecurityTranscript.digest(DOMAIN, *parts.toTypedArray())
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
        require(verify(hostIdentity.signingPublicKey, digest(decoded), decoded.profile.leaseSignature)) {
            "Internet session lease signature is invalid"
        }
    }

    private fun MutableList<ByteArray>.addNullable(value: String?) {
        add(byteArrayOf(if (value == null) 0 else 1))
        if (value != null) add(text(value))
    }

    private fun text(value: String): ByteArray = value.toByteArray(StandardCharsets.UTF_8)
    private fun u64(value: Long): ByteArray = SecurityTranscript.uint64(value)
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
            "signaling_url",
            "signaling_session_id",
            "session_epoch",
            "identity_epoch",
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
        require(json.toByteArray(Charsets.UTF_8).size <= MAX_PROFILE_BYTES) { "Internet profile is too large" }
        val root = JsonParser.parseString(json).asJsonObject
        require(root.keySet() == ROOT_KEYS) {
            "Internet profile contains missing or unknown fields"
        }
        require(root.requiredInt("version") == VERSION) { "Unsupported Internet profile version" }
        val pairingIdentifier = root.requiredString("pairing_id", MAX_IDENTIFIER_BYTES)
        val signalingUrl = root.requiredString("signaling_url", MAX_URL_BYTES)
        val allowInsecure = root.requiredBoolean("allow_insecure_for_testing")
        validateSignalingUrl(signalingUrl, allowInsecure, debuggable)
        val signalingToken = root.requiredString("signaling_token", MAX_TOKEN_BYTES)
        require(signalingToken.length >= MIN_SIGNALING_TOKEN_BYTES) { "Signaling token is invalid" }
        val ice = root.requiredArray("ice_servers")
        require(ice.size() in 1..MAX_ICE_SERVERS) { "ICE server count is invalid" }
        val urls = mutableListOf<List<String>>()
        val credentials = mutableListOf<Pair<String?, String?>>()
        ice.forEach { element ->
            val server = element.asJsonObject
            require(server.keySet() == ICE_KEYS) { "ICE server contains missing or unknown fields" }
            val serverUrls =
                server.requiredArray("urls").map {
                    require(it.isJsonPrimitive && it.asJsonPrimitive.isString) { "ICE URL must be a string" }
                    it.asString
                }
            require(serverUrls.isNotEmpty() && serverUrls.size <= MAX_ICE_URLS) { "ICE URL count is invalid" }
            require(serverUrls.all { it.length <= MAX_URL_BYTES }) { "ICE URL is too large" }
            val username = server.nullableString("username", MAX_CREDENTIAL_BYTES)
            val credential = server.nullableString("credential", MAX_CREDENTIAL_BYTES)
            IceServer(serverUrls, username, credential)
            urls += serverUrls
            credentials += username to credential
        }
        val sessionId = root.requiredString("signaling_session_id", MAX_IDENTIFIER_BYTES)
        val protocolSessionId = root.requiredBase64("protocol_session_id", 1..MAX_IDENTIFIER_BYTES)
        val profile =
            StoredInternetSessionProfile(
                pairingIdentifier = pairingIdentifier,
                pinnedHostId = root.requiredString("pinned_host_id", MAX_IDENTIFIER_BYTES),
                signalingUrl = signalingUrl,
                signalingSessionId = sessionId,
                authoritativeSessionEpoch = root.requiredPositiveLong("session_epoch"),
                identityEpoch = root.requiredPositiveLong("identity_epoch"),
                transcriptContext = root.requiredBase64("transcript_context", TRANSCRIPT_BYTES..TRANSCRIPT_BYTES),
                protocolSessionId = protocolSessionId,
                iceServerUrls = urls,
                allowInsecureForTesting = allowInsecure,
                leaseHostKeyId = root.requiredString("lease_host_key_id", MAX_IDENTIFIER_BYTES),
                leaseSignature = root.requiredBase64("lease_signature", 1..MAX_SIGNATURE_BYTES),
            )
        return DecodedInternetProfile(
            profile,
            ImportedInternetSecrets(signalingToken, credentials),
        )
    }

    fun encodePublic(profile: StoredInternetSessionProfile): String =
        JsonObject().apply {
            addProperty("version", VERSION)
            addProperty("pairing_id", profile.pairingIdentifier)
            addProperty("pinned_host_id", profile.pinnedHostId)
            addProperty("signaling_url", profile.signalingUrl)
            addProperty("signaling_session_id", profile.signalingSessionId)
            addProperty("session_epoch", profile.authoritativeSessionEpoch)
            addProperty("identity_epoch", profile.identityEpoch)
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

    fun encodeSecrets(secrets: ImportedInternetSecrets): String =
        JsonObject().apply {
            addProperty("signaling_token", secrets.signalingToken)
            add(
                "turn_credentials",
                JsonArray().apply {
                    secrets.turnCredentials.forEach { value ->
                        add(JsonObject().apply { addNullable("username", value.first); addNullable("credential", value.second) })
                    }
                },
            )
        }.toString()

    fun decodeSecrets(json: String, expectedIceServers: Int): ImportedInternetSecrets {
        val root = JsonParser.parseString(json).asJsonObject
        require(root.keySet() == SECRET_KEYS) { "Stored Internet credentials are malformed" }
        val credentials = root.requiredArray("turn_credentials")
        require(credentials.size() == expectedIceServers) { "Stored ICE credentials do not match the lease" }
        return ImportedInternetSecrets(
            signalingToken = root.requiredString("signaling_token", MAX_TOKEN_BYTES),
            turnCredentials =
                credentials.map { element ->
                    val value = element.asJsonObject
                    require(value.keySet() == setOf("username", "credential")) { "Stored TURN credential is malformed" }
                    value.nullableString("username", MAX_CREDENTIAL_BYTES) to value.nullableString("credential", MAX_CREDENTIAL_BYTES)
                },
        )
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
