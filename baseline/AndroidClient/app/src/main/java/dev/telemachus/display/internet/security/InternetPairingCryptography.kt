package dev.telemachus.display.internet.security

import java.math.BigInteger
import java.security.AlgorithmParameters
import java.security.KeyFactory
import java.security.KeyPair
import java.security.KeyPairGenerator
import java.security.MessageDigest
import java.security.PrivateKey
import java.security.SecureRandom
import java.security.Signature
import java.security.interfaces.ECPublicKey
import java.security.spec.ECGenParameterSpec
import java.security.spec.ECParameterSpec
import java.security.spec.ECPoint
import java.security.spec.ECPublicKeySpec
import javax.crypto.KeyAgreement
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

internal fun generateEphemeral(random: SecureRandom): KeyPair =
    KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp256r1"), random) }.generateKeyPair()

internal fun publicPoint(pair: KeyPair): ByteArray {
    val key = pair.public as ECPublicKey
    return byteArrayOf(4) + coordinate(key.w.affineX) + coordinate(key.w.affineY)
}

internal fun validateP256PublicKey(encoded: ByteArray) {
    decodePublicKey(encoded)
}

internal fun ecdh(privateKey: PrivateKey, publicKey: ByteArray): ByteArray =
    KeyAgreement.getInstance("ECDH").run { init(privateKey); doPhase(decodePublicKey(publicKey), true); generateSecret() }

internal fun verify(publicKey: ByteArray, digest: ByteArray, signature: ByteArray): Boolean {
    if (digest.size != SHA256_DIGEST_BYTES ||
        publicKey.size != PUBLIC_KEY_BYTES || publicKey[0] != 4.toByte() ||
        signature.size !in MIN_ECDSA_DER_BYTES..MAX_ECDSA_DER_BYTES
    ) {
        return false
    }
    return runCatching {
        Signature.getInstance("NONEwithECDSA").run {
            initVerify(decodePublicKey(publicKey))
            update(digest)
            verify(signature)
        }
    }.getOrDefault(false)
}

internal fun hkdf(input: ByteArray, salt: ByteArray, info: ByteArray): ByteArray {
    val extract = hmac(salt, input)
    return try {
        hmac(extract, info + byteArrayOf(1))
    } finally {
        extract.fill(0)
    }
}

internal fun hmac(key: ByteArray, value: ByteArray): ByteArray =
    Mac.getInstance("HmacSHA256").run { init(SecretKeySpec(key, "HmacSHA256")); doFinal(value) }

internal fun pairingSha256(value: ByteArray): ByteArray = MessageDigest.getInstance("SHA-256").digest(value)

internal fun ByteArray.toPairingHex(): String = joinToString("") { "%02x".format(it) }

private fun coordinate(value: BigInteger): ByteArray {
    val signed = value.toByteArray()
    val unsigned = if (signed.size == COORDINATE_BYTES + 1 && signed[0] == 0.toByte()) signed.copyOfRange(1, signed.size) else signed
    require(unsigned.size <= COORDINATE_BYTES) { "Invalid P-256 coordinate" }
    return ByteArray(COORDINATE_BYTES - unsigned.size) + unsigned
}

private fun decodePublicKey(encoded: ByteArray): ECPublicKey {
    require(encoded.size == PUBLIC_KEY_BYTES && encoded[0] == 4.toByte()) { "Invalid uncompressed P-256 public key" }
    val parameters = AlgorithmParameters.getInstance("EC").apply { init(ECGenParameterSpec("secp256r1")) }
    val spec = parameters.getParameterSpec(ECParameterSpec::class.java)
    val point = ECPoint(BigInteger(1, encoded.copyOfRange(1, 33)), BigInteger(1, encoded.copyOfRange(33, 65)))
    return KeyFactory.getInstance("EC").generatePublic(ECPublicKeySpec(point, spec)) as ECPublicKey
}

private const val COORDINATE_BYTES = 32
private const val PUBLIC_KEY_BYTES = 65
private const val SHA256_DIGEST_BYTES = 32
private const val MIN_ECDSA_DER_BYTES = 8
private const val MAX_ECDSA_DER_BYTES = 80
