package dev.telemachus.display

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class InternetAcceptanceHostFixtureContractTest {
    @Test
    fun `host fixture reuses production request transcript canonicalization`() {
        val source = source(INTERNET_ACCEPTANCE_HOST_FIXTURE)
        val pairingParts = extractMethod(source, "private fun pairingParts")

        assertTrue(source.contains("import dev.telemachus.display.internet.security.canonicalPairingRequestParts"))
        assertTrue(pairingParts.contains("canonicalPairingRequestParts("))
        assertTrue(pairingParts.contains("offer.offer"))
        assertTrue(pairingParts.contains("request.deviceIdentity"))
        assertTrue(pairingParts.contains("request.deviceName"))
        assertTrue(pairingParts.contains("request.deviceEphemeralPublicKey"))
        assertFalse(
            "Fixture must not hard-code pairing capability lists that can drift from the production offer",
            source.contains("canonicalList(listOf") || source.contains("application_e2ee") || source.contains("media_data_channel"),
        )
    }

    @Test
    fun `host fixture still enforces request signature and bootstrap mac`() {
        val source = source(INTERNET_ACCEPTANCE_HOST_FIXTURE)
        val accept = extractMethod(source, "fun accept")

        assertTrue(accept.contains("check(verify(request.deviceIdentity.signingPublicKey"))
        assertTrue(accept.contains("transcriptDigest(REQUEST_DOMAIN, *parts), request.requestSignature"))
        assertTrue(accept.contains("val expectedMac = hmac(offer.oneTimeCredential"))
        assertTrue(accept.contains("transcriptDigest(BOOTSTRAP_DOMAIN, *(parts + request.requestSignature))"))
        assertTrue(accept.contains("check(MessageDigest.isEqual(expectedMac, request.bootstrapMac))"))
    }

    private fun source(relativePath: String): String {
        var current = File(requireNotNull(System.getProperty("user.dir"))).canonicalFile
        repeat(8) {
            listOf(relativePath, "baseline/AndroidClient/$relativePath")
                .map(current::resolve)
                .firstOrNull(File::isFile)
                ?.let { return it.readText() }
            current = current.parentFile?.canonicalFile ?: current
        }
        error("$relativePath not found from " + System.getProperty("user.dir"))
    }

    private fun extractMethod(source: String, signature: String): String {
        val start = source.indexOf(signature)
        require(start >= 0) { "$signature not found" }
        val bodyStart = source.indexOf('{', start)
        require(bodyStart >= 0) { "$signature has no body" }
        var depth = 0
        for (index in bodyStart until source.length) {
            when (source[index]) {
                '{' -> depth++
                '}' -> {
                    depth--
                    if (depth == 0) return source.substring(start, index + 1)
                }
            }
        }
        error("$signature body is not closed")
    }

    private companion object {
        const val INTERNET_ACCEPTANCE_HOST_FIXTURE =
            "app/src/androidTest/java/dev/telemachus/display/InternetAcceptanceHostFixture.kt"
    }
}
