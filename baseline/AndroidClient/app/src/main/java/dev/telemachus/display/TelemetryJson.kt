package dev.telemachus.display

/** Stable JSONL encoding for logcat collection and soak-test ingestion. */
object TelemetryJson {
    fun encode(
        event: String,
        timestampMs: Long,
        fields: Map<String, Any?> = emptyMap(),
    ): String {
        require(event.isNotBlank()) { "event must not be blank" }
        require(fields.keys.none { it == "schema_version" || it == "timestamp_ms" || it == "event" }) {
            "fields must not replace schema_version, timestamp_ms, or event"
        }
        val values = linkedMapOf<String, Any?>(
            "schema_version" to 1,
            "timestamp_ms" to timestampMs,
            "event" to event,
        )
        values.putAll(fields)
        return values.entries.joinToString(separator = ",", prefix = "{", postfix = "}") { (key, value) ->
            "\"${escape(key)}\":${encodeValue(value)}"
        }
    }

    private fun encodeValue(value: Any?): String =
        when (value) {
            null -> "null"
            is Boolean -> value.toString()
            is Double -> requireFinite(value)
            is Float -> requireFinite(value)
            is Number -> value.toString()
            else -> "\"${escape(value.toString())}\""
        }

    private fun requireFinite(value: Number): String {
        val number = value.toDouble()
        require(number.isFinite()) { "telemetry numbers must be finite" }
        return value.toString()
    }

    private fun escape(value: String): String =
        buildString(value.length) {
            value.forEach { character ->
                when (character) {
                    '\\' -> append("\\\\")
                    '"' -> append("\\\"")
                    '\n' -> append("\\n")
                    '\r' -> append("\\r")
                    '\t' -> append("\\t")
                    else -> {
                        if (character.code < 0x20) {
                            append("\\u")
                            append(character.code.toString(16).padStart(4, '0'))
                        } else {
                            append(character)
                        }
                    }
                }
            }
        }
}
