package dev.telemachus.display.internet.security

import com.google.gson.JsonObject
import com.google.gson.JsonParser
import java.nio.charset.StandardCharsets
import java.nio.file.Files
import java.nio.file.Path
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.Base64

internal class SharedPairingWireFixture private constructor(
    private val root: JsonObject,
) {
    data class WireValue(
        val utf8: String,
        val byteLength: Int,
        val sha256: String,
    )

    data class NegativeCase(
        val name: String,
        val category: String,
        val target: String,
        val wireUtf8: String,
        val sha256: String,
    )

    val schema: String = root.string("schema")
    val fixtureScope: String = root.string("fixture_scope")
    val protocolVersion: Int = root.get("protocol_version").asInt
    val negativeCategories: Set<String> = root.getAsJsonArray("negative_cases")
        .map { it.asJsonObject.string("category") }
        .toSet()

    fun wire(name: String): WireValue = root.getAsJsonObject("wire").getAsJsonObject(name).let {
        WireValue(it.string("utf8"), it.get("byte_length").asInt, it.string("sha256"))
    }

    fun expected(name: String): String = root.getAsJsonObject("expected").string(name)

    fun material(name: String): String = root.getAsJsonObject("test_material").string(name)

    fun materialInt(name: String): Int = root.getAsJsonObject("test_material").get(name).asInt

    fun negative(name: String): NegativeCase = root.getAsJsonArray("negative_cases")
        .map { it.asJsonObject }
        .firstOrNull { it.string("name") == name }
        ?.let {
            NegativeCase(
                it.string("name"),
                it.string("category"),
                it.string("target"),
                it.string("wire_utf8"),
                it.string("sha256"),
            )
        }
        ?: error("Missing negative pairing fixture: $name")

    companion object {
        fun load(): SharedPairingWireFixture {
            val relative = Path.of("contracts", "fixtures", "pairing", "v1", "wire.json")
            val fixturePath = generateSequence(Path.of(System.getProperty("user.dir")).toAbsolutePath()) { it.parent }
                .map { it.resolve(relative) }
                .firstOrNull(Files::isRegularFile)
                ?: error("Unable to locate shared pairing fixture from ${System.getProperty("user.dir")}")
            val root = JsonParser.parseString(String(Files.readAllBytes(fixturePath), StandardCharsets.UTF_8)).asJsonObject
            return SharedPairingWireFixture(root)
        }
    }
}

internal class FixedFillSecureRandom(
    private val fillByte: Byte,
) : SecureRandom() {
    override fun nextBytes(bytes: ByteArray) {
        bytes.fill(fillByte)
    }
}

internal fun decodePairingFixtureBase64URL(value: String): ByteArray {
    require(value.isNotEmpty() && '=' !in value && value.all { it.isLetterOrDigit() || it == '-' || it == '_' }) {
        "Fixture value is not canonical base64url"
    }
    val decoded = Base64.getUrlDecoder().decode(value)
    require(Base64.getUrlEncoder().withoutPadding().encodeToString(decoded) == value) {
        "Fixture value is not canonical base64url"
    }
    return decoded
}

internal fun pairingFixtureSha256Hex(value: String): String =
    MessageDigest.getInstance("SHA-256")
        .digest(value.toByteArray(StandardCharsets.UTF_8))
        .joinToString("") { "%02x".format(it) }

private fun JsonObject.string(name: String): String =
    get(name)?.takeIf { it.isJsonPrimitive && it.asJsonPrimitive.isString }?.asString
        ?: error("Pairing fixture field $name must be a string")
