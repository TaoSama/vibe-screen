package dev.telemachus.display.internet.security

import com.google.gson.JsonObject
import com.google.gson.JsonParser
import java.nio.charset.StandardCharsets
import java.nio.file.Files
import java.nio.file.Path

internal class SharedChannelSecurityFixture private constructor(private val root: JsonObject) {
    val schema: String = root.string("schema")
    val sessionId: String = root.getAsJsonObject("session").string("id")
    val sessionEpoch: Long = root.getAsJsonObject("session").get("epoch").asLong

    fun input(name: String): ByteArray = root.getAsJsonObject("input").string(name).hexBytes()
    fun keyId(stage: String): String = root.getAsJsonObject(stage).string("key_id")
    fun keyMaterial(stage: String): ByteArray = root.getAsJsonObject(stage).string("keys").hexBytes()
    fun record(name: String): Record = root.getAsJsonObject("records").getAsJsonObject(name).let {
        Record(payload = it.string("payload").hexBytes(), encoded = it.string("record").hexBytes())
    }

    data class Record(val payload: ByteArray, val encoded: ByteArray)

    companion object {
        fun load(): SharedChannelSecurityFixture {
            val relative = Path.of("contracts", "fixtures", "security", "v1", "channel-records.json")
            val workingDirectory = System.getProperty("user.dir")
            val fixturePath = generateSequence(Path.of(workingDirectory).toAbsolutePath()) { it.parent }
                .map { it.resolve(relative) }
                .firstOrNull(Files::isRegularFile)
                ?: error("Unable to locate shared channel security fixture from " + workingDirectory)
            val root = JsonParser.parseString(String(Files.readAllBytes(fixturePath), StandardCharsets.UTF_8)).asJsonObject
            return SharedChannelSecurityFixture(root)
        }
    }
}

private fun JsonObject.string(name: String): String =
    get(name)?.takeIf { it.isJsonPrimitive && it.asJsonPrimitive.isString }?.asString
        ?: error("Channel security fixture field " + name + " must be a string")

private fun String.hexBytes(): ByteArray {
    require(length % 2 == 0 && all { it.digitToIntOrNull(16) != null }) { "Fixture value must be lowercase hex" }
    return chunked(2).map { it.toInt(16).toByte() }.toByteArray()
}
