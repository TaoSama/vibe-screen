package dev.telemachus.display.internet.security

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.math.BigInteger
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.MessageDigest
import java.security.PrivateKey
import java.security.Signature
import java.security.interfaces.ECPublicKey
import java.security.spec.ECGenParameterSpec
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

data class AndroidPublicIdentity(
    val deviceId: String,
    val keyId: String,
    val keyEpoch: Long,
    val signingPublicKey: ByteArray,
) {
    fun rotationNonceHash(nonce: ByteArray): ByteArray {
        require(nonce.size >= 16) { "Identity rotation requires at least 16 nonce bytes" }
        val identity =
            SecurityTranscript.digest(
                "vibescreen/public-identity/v1",
                deviceId.toByteArray(),
                keyId.toByteArray(),
                SecurityTranscript.uint64(keyEpoch),
                ALGORITHM.toByteArray(),
                signingPublicKey,
            )
        return sha256(
            SecurityTranscript.digest("vibescreen/key-rotation-nonce/v1", identity, nonce),
        )
    }

    companion object {
        const val ALGORITHM = "ECDSA_P256_SHA256"
    }
}

internal fun AndroidPublicIdentity.matches(other: InternetPairingIdentity): Boolean =
    deviceId == other.deviceId &&
        keyId == other.keyId &&
        keyEpoch == other.keyEpoch &&
        other.signatureAlgorithm == AndroidPublicIdentity.ALGORITHM &&
        MessageDigest.isEqual(signingPublicKey, other.signingPublicKey)

internal fun AndroidPublicIdentity.toPairingIdentity(): InternetPairingIdentity =
    InternetPairingIdentity(
        deviceId = deviceId,
        keyId = keyId,
        keyEpoch = keyEpoch,
        signatureAlgorithm = AndroidPublicIdentity.ALGORITHM,
        signingPublicKey = signingPublicKey.copyOf(),
    )

class AndroidDeviceIdentity internal constructor(
    val publicIdentity: AndroidPublicIdentity,
    private val keyAlias: String,
) {
    /** Signs a Protocol v1 SHA-256 transcript digest as ASN.1 DER. */
    fun signTranscriptDigest(digest: ByteArray): ByteArray {
        require(digest.size == SHA256_BYTES) { "Identity signatures require a SHA-256 transcript digest" }
        val keyStore = androidKeyStore()
        val privateKey = checkNotNull(keyStore.getKey(keyAlias, null)) { "Identity private key is unavailable" }
        return Signature
            .getInstance("NONEwithECDSA")
            .apply {
                initSign(privateKey as java.security.PrivateKey)
                update(digest)
            }.sign()
    }
}

internal interface DeviceIdentityStore {
    fun loadExisting(deviceId: String, keyEpoch: Long): AndroidDeviceIdentity?

    fun loadOrCreateForPairing(deviceId: String, keyEpoch: Long = 1): AndroidDeviceIdentity

    fun delete(deviceId: String, keyEpoch: Long)
}

class AndroidDeviceIdentityStore : DeviceIdentityStore {
    @Synchronized
    override fun loadExisting(
        deviceId: String,
        keyEpoch: Long,
    ): AndroidDeviceIdentity? {
        require(deviceId.isNotBlank() && keyEpoch > 0) { "Device ID and positive key epoch are required" }
        val alias = identityAlias(deviceId, keyEpoch)
        val keyStore = androidKeyStore()
        if (!keyStore.containsAlias(alias)) return null
        return loadIdentity(keyStore, deviceId, keyEpoch, alias)
    }

    @Synchronized
    override fun loadOrCreateForPairing(
        deviceId: String,
        keyEpoch: Long,
    ): AndroidDeviceIdentity {
        require(deviceId.isNotBlank() && keyEpoch > 0) { "Device ID and positive key epoch are required" }
        val alias = identityAlias(deviceId, keyEpoch)
        val keyStore = androidKeyStore()
        if (!keyStore.containsAlias(alias)) {
            KeyPairGenerator
                .getInstance(KeyProperties.KEY_ALGORITHM_EC, ANDROID_KEYSTORE)
                .apply {
                    initialize(
                        KeyGenParameterSpec
                            .Builder(alias, KeyProperties.PURPOSE_SIGN or KeyProperties.PURPOSE_VERIFY)
                            .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
                            .setDigests(KeyProperties.DIGEST_NONE, KeyProperties.DIGEST_SHA256)
                            .setUserAuthenticationRequired(false)
                            .build(),
                    )
                }.generateKeyPair()
        }
        return loadIdentity(keyStore, deviceId, keyEpoch, alias)
    }

    private fun loadIdentity(
        keyStore: KeyStore,
        deviceId: String,
        keyEpoch: Long,
        alias: String,
    ): AndroidDeviceIdentity {
        check(keyStore.getKey(alias, null) is PrivateKey) { "Identity private key is unavailable; pair again" }
        val publicKey = keyStore.getCertificate(alias)?.publicKey as? ECPublicKey
            ?: error("Identity public key is unavailable")
        val encoded = byteArrayOf(UNCOMPRESSED_POINT) + coordinate(publicKey.w.affineX) + coordinate(publicKey.w.affineY)
        check(encoded.size == PUBLIC_KEY_BYTES) { "Android Keystore returned an unsupported P-256 public key" }
        return AndroidDeviceIdentity(
            AndroidPublicIdentity(deviceId, sha256(encoded).toHex(), keyEpoch, encoded),
            alias,
        )
    }

    @Synchronized
    override fun delete(
        deviceId: String,
        keyEpoch: Long,
    ) {
        androidKeyStore().deleteEntry(identityAlias(deviceId, keyEpoch))
    }

    private fun identityAlias(deviceId: String, epoch: Long): String =
        "$IDENTITY_ALIAS_PREFIX.${sha256(deviceId.toByteArray()).toHex()}.$epoch"

    private fun coordinate(value: BigInteger): ByteArray {
        val signed = value.toByteArray()
        val unsigned = if (signed.size == COORDINATE_BYTES + 1 && signed[0] == 0.toByte()) signed.copyOfRange(1, signed.size) else signed
        require(unsigned.size <= COORDINATE_BYTES) { "Invalid P-256 coordinate" }
        return ByteArray(COORDINATE_BYTES - unsigned.size) + unsigned
    }
}

/** Encrypts persisted credentials with a non-exportable AndroidKeyStore AES key. */
class AndroidSecretStore(
    context: Context,
) {
    private val preferences = context.getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)

    @Synchronized
    fun persist(
        name: String,
        secret: ByteArray,
    ) {
        require(name.isNotBlank() && secret.isNotEmpty()) { "Secret name and value are required" }
        val cipher = Cipher.getInstance(AES_TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, wrappingKey())
        cipher.updateAAD(name.toByteArray())
        val ciphertext = cipher.doFinal(secret)
        check(
            preferences
                .edit()
                .putString("$name.iv", cipher.iv.base64())
                .putString("$name.ciphertext", ciphertext.base64())
                .commit(),
        ) { "Failed to persist encrypted security material" }
    }

    @Synchronized
    fun load(name: String): ByteArray? {
        val iv = preferences.getString("$name.iv", null)?.decodeBase64() ?: return null
        val ciphertext = preferences.getString("$name.ciphertext", null)?.decodeBase64() ?: return null
        val cipher = Cipher.getInstance(AES_TRANSFORMATION)
        cipher.init(Cipher.DECRYPT_MODE, wrappingKey(), GCMParameterSpec(GCM_TAG_BITS, iv))
        cipher.updateAAD(name.toByteArray())
        return cipher.doFinal(ciphertext)
    }

    @Synchronized
    fun delete(name: String) {
        check(preferences.edit().remove("$name.iv").remove("$name.ciphertext").commit()) {
            "Failed to delete encrypted security material"
        }
    }

    private fun wrappingKey(): SecretKey {
        val keyStore = androidKeyStore()
        (keyStore.getKey(SECRET_KEY_ALIAS, null) as? SecretKey)?.let { return it }
        return KeyGenerator
            .getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEYSTORE)
            .apply {
                init(
                    KeyGenParameterSpec
                        .Builder(SECRET_KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                        .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                        .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                        .setKeySize(256)
                        .setRandomizedEncryptionRequired(true)
                        .build(),
                )
            }.generateKey()
    }

    private fun ByteArray.base64(): String = Base64.encodeToString(this, Base64.NO_WRAP)

    private fun String.decodeBase64(): ByteArray = Base64.decode(this, Base64.NO_WRAP)
}

data class ActiveAndroidSecuritySession(
    val identity: AndroidDeviceIdentity,
    val sessionEpoch: Long,
    val trafficKeys: SessionTrafficKeys,
)

/** Product-facing composition point for identity and session key lifecycle. */
class AndroidSessionSecurity private constructor(
    private val deviceId: String,
    private val identityStore: DeviceIdentityStore,
    stateStore: SecurityStateStore,
) {
    private val lifecycle = SecurityLifecycle(stateStore)

    constructor(
        deviceId: String,
        context: Context,
        stateStore: SecurityStateStore = SharedPreferencesSecurityStateStore(context, deviceId),
    ) : this(deviceId, AndroidDeviceIdentityStore(), stateStore)

    internal constructor(
        deviceId: String,
        stateStore: SecurityStateStore,
        identityStore: DeviceIdentityStore,
    ) : this(deviceId, identityStore, stateStore)

    fun startSession(
        pairingIdentifier: String,
        expectedIdentity: InternetPairingIdentity,
        authoritativeSessionEpoch: Long,
        sharedSecret: ByteArray,
        bootstrapSecret: ByteArray,
        transcriptContext: ByteArray,
    ): ActiveAndroidSecuritySession {
        val identity = requireExistingAuthorizedIdentity(expectedIdentity)
        val sessionEpoch =
            lifecycle.reserveSessionEpoch(
                pairingSecurityScope(deviceId, pairingIdentifier),
                expectedIdentity.keyEpoch,
                authoritativeSessionEpoch,
            )
        val keys = TrafficKeyDerivation.initial(sharedSecret, bootstrapSecret, transcriptContext)
        return ActiveAndroidSecuritySession(identity, sessionEpoch, keys)
    }

    fun rotateTrafficKeys(
        current: SessionTrafficKeys,
        updateNonce: ByteArray,
    ): SessionTrafficKeys {
        check(current.keyEpoch < Long.MAX_VALUE) { "Traffic-key epoch exhausted" }
        return TrafficKeyDerivation.rotate(current, current.keyEpoch + 1, updateNonce)
    }

    fun reserveNonce(
        pairingIdentifier: String,
        identityEpoch: Long,
        channel: Int,
        senderRole: Int,
        keyEpoch: Long,
    ): ByteArray =
        lifecycle.reserveNonce(
            pairingSecurityScope(deviceId, pairingIdentifier),
            identityEpoch,
            channel,
            senderRole,
            keyEpoch,
        )

    fun reserveNextIdentityEpoch(): Long = lifecycle.reserveNextIdentityEpoch()

    fun authorizeIdentity(identity: InternetPairingIdentity) {
        require(identity.deviceId == deviceId) { "Authorized identity belongs to another local device" }
        val existing = checkNotNull(identityStore.loadExisting(deviceId, identity.keyEpoch)) {
            "Authorized identity private key is unavailable; pair again"
        }
        require(existing.publicIdentity.matches(identity)) {
            "Authorized identity does not match the Android Keystore key; pair again"
        }
        lifecycle.authorizeIdentityEpoch(identity.keyEpoch, identity.keyId)
    }

    internal fun requireExistingAuthorizedIdentity(expected: InternetPairingIdentity): AndroidDeviceIdentity {
        require(expected.deviceId == deviceId) { "Stored identity belongs to another local device" }
        val identity = requireExistingAuthorizedIdentity(expected.keyEpoch)
        require(identity.publicIdentity.matches(expected)) {
            "Stored pairing identity does not match the Android Keystore key; pair again"
        }
        return identity
    }

    private fun requireExistingAuthorizedIdentity(identityEpoch: Long): AndroidDeviceIdentity {
        val expectedKeyId = lifecycle.requireAuthorizedIdentityKeyId(identityEpoch)
        val identity = checkNotNull(identityStore.loadExisting(deviceId, identityEpoch)) {
            "Authorized identity private key is unavailable; pair again"
        }
        require(MessageDigest.isEqual(identity.publicIdentity.keyId.toByteArray(), expectedKeyId.toByteArray())) {
            "Authorized identity does not match the durable key binding; pair again"
        }
        return identity
    }

    fun <T> withFreshSessionEpochCandidate(
        pairingIdentifier: String,
        identity: InternetPairingIdentity,
        sessionEpoch: Long,
        block: () -> T,
    ): T {
        requireExistingAuthorizedIdentity(identity)
        return lifecycle.withFreshSessionEpochCandidate(
            pairingSecurityScope(deviceId, pairingIdentifier),
            identity.keyEpoch,
            sessionEpoch,
            block,
        )
    }

    fun <T> withActiveSessionEpoch(
        pairingIdentifier: String,
        identityEpoch: Long,
        sessionEpoch: Long,
        block: () -> T,
    ): T =
        lifecycle.withActiveSessionEpoch(
            pairingSecurityScope(deviceId, pairingIdentifier),
            identityEpoch,
            sessionEpoch,
            block,
        )

    fun <T> withReservedSessionNonce(
        pairingIdentifier: String,
        identityEpoch: Long,
        sessionEpoch: Long,
        channel: Int,
        senderRole: Int,
        keyEpoch: Long,
        block: (ByteArray) -> T,
    ): T =
        lifecycle.withReservedSessionNonce(
            pairingSecurityScope(deviceId, pairingIdentifier),
            identityEpoch,
            sessionEpoch,
            channel,
            senderRole,
            keyEpoch,
            block,
        )

    fun consumeRotationNonce(
        identityEpoch: Long,
        authority: AndroidPublicIdentity,
        nonce: ByteArray,
    ) {
        lifecycle.consumeRotationNonceHash(
            identityEpoch,
            authority.rotationNonceHash(nonce),
        )
    }

    fun revoke(
        pairingIdentifier: String,
        sequence: Long,
        identityEpoch: Long,
    ) {
        // Persist revocation before deleting the private key so deletion
        // failures cannot accidentally re-authorize the local identity.
        lifecycle.applyRevocation(
            pairingSecurityScope(deviceId, pairingIdentifier),
            identityEpoch,
            sequence,
        )
        identityStore.delete(deviceId, identityEpoch)
    }
}

private fun androidKeyStore(): KeyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }

private fun sha256(value: ByteArray): ByteArray = MessageDigest.getInstance("SHA-256").digest(value)

private fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it) }

private const val ANDROID_KEYSTORE = "AndroidKeyStore"
private const val IDENTITY_ALIAS_PREFIX = "dev.telemachus.display.phase3.identity.v1"
private const val SECRET_KEY_ALIAS = "dev.telemachus.display.phase3.secret-wrapping.v1"
private const val PREFERENCES_NAME = "phase3_security_secrets"
private const val AES_TRANSFORMATION = "AES/GCM/NoPadding"
private const val GCM_TAG_BITS = 128
private const val SHA256_BYTES = 32
private const val COORDINATE_BYTES = 32
private const val PUBLIC_KEY_BYTES = 65
private const val UNCOMPRESSED_POINT: Byte = 0x04
