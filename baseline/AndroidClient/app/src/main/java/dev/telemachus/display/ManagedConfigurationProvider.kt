package dev.telemachus.display

import android.content.Context
import android.content.RestrictionsManager
import android.os.Bundle
import dev.telemachus.display.protocol.ProtocolV1Session

internal object ManagedConfigurationKeys {
    const val CLIPBOARD_ALLOWED = "ClipboardAllowed"
    const val FILE_TRANSFER_ALLOWED = "FileTransferAllowed"
    const val AUDIO_ALLOWED = "AudioAllowed"
    const val WAKE_ALLOWED = "WakeAllowed"
    const val CUSTOM_GESTURES_ALLOWED = "CustomGesturesAllowed"
    const val HOST_ACTIONS_ALLOWED = "HostActionsAllowed"
    const val MAXIMUM_FILE_BYTES = "MaximumFileBytes"
    const val ALLOWED_HOSTS = "AllowedHosts"
    const val DENIED_HOSTS = "DeniedHosts"
}

internal class ManagedConfigurationProvider(
    private val restrictions: () -> Map<String, Any?>?,
) {
    constructor(context: Context) : this(
        restrictions = {
            val manager = context.getSystemService(Context.RESTRICTIONS_SERVICE) as? RestrictionsManager
            manager?.applicationRestrictions?.toManagedConfigurationMap()
        },
    )

    fun loadPolicy(): ProtocolV1Session.ManagedPolicy =
        try {
            ManagedConfigurationSchema.parse(restrictions())
                ?.toManagedPolicy()
                ?: ProtocolV1Session.ManagedPolicy.UNMANAGED
        } catch (_: ManagedConfigurationParseException) {
            failClosedPolicy
        }
}

internal data class ManagedConfigurationSchema(
    val clipboardAllowed: Boolean,
    val fileTransferAllowed: Boolean,
    val audioAllowed: Boolean,
    val wakeAllowed: Boolean,
    val customGesturesAllowed: Boolean,
    val hostActionsAllowed: Boolean,
    val maximumFileBytes: Long,
    val allowedHosts: Set<String>,
    val deniedHosts: Set<String>,
) {
    fun toManagedPolicy(): ProtocolV1Session.ManagedPolicy =
        ProtocolV1Session.ManagedPolicy(
            isManaged = true,
            clipboardAllowed = clipboardAllowed,
            fileTransferAllowed = fileTransferAllowed,
            audioAllowed = audioAllowed,
            wakeAllowed = wakeAllowed,
            customGesturesAllowed = customGesturesAllowed,
            hostActionsAllowed = hostActionsAllowed,
            maximumFileBytes = maximumFileBytes,
            allowedHosts = allowedHosts,
            deniedHosts = deniedHosts,
        )

    companion object {
        fun parse(values: Map<String, Any?>?): ManagedConfigurationSchema? {
            if (values == null || values.isEmpty()) return null
            return ManagedConfigurationSchema(
                clipboardAllowed = requiredBoolean(values, ManagedConfigurationKeys.CLIPBOARD_ALLOWED),
                fileTransferAllowed = requiredBoolean(values, ManagedConfigurationKeys.FILE_TRANSFER_ALLOWED),
                audioAllowed = requiredBoolean(values, ManagedConfigurationKeys.AUDIO_ALLOWED),
                wakeAllowed = requiredBoolean(values, ManagedConfigurationKeys.WAKE_ALLOWED),
                customGesturesAllowed = requiredBoolean(values, ManagedConfigurationKeys.CUSTOM_GESTURES_ALLOWED),
                hostActionsAllowed = requiredBoolean(values, ManagedConfigurationKeys.HOST_ACTIONS_ALLOWED),
                maximumFileBytes = optionalNonNegativeLong(values, ManagedConfigurationKeys.MAXIMUM_FILE_BYTES) ?: 0L,
                allowedHosts = optionalStringSet(values, ManagedConfigurationKeys.ALLOWED_HOSTS).orEmpty(),
                deniedHosts = optionalStringSet(values, ManagedConfigurationKeys.DENIED_HOSTS).orEmpty(),
            )
        }

        private fun requiredBoolean(values: Map<String, Any?>, key: String): Boolean {
            if (!values.containsKey(key)) return false
            val value = values[key]
            if (value !is Boolean) throw ManagedConfigurationParseException(key)
            return value
        }

        private fun optionalNonNegativeLong(values: Map<String, Any?>, key: String): Long? {
            if (!values.containsKey(key)) return null
            val value = values[key]
            val longValue =
                when (value) {
                    is Byte -> value.toLong()
                    is Short -> value.toLong()
                    is Int -> value.toLong()
                    is Long -> value
                    else -> throw ManagedConfigurationParseException(key)
                }
            if (longValue < 0L) throw ManagedConfigurationParseException(key)
            return longValue
        }

        private fun optionalStringSet(values: Map<String, Any?>, key: String): Set<String>? {
            if (!values.containsKey(key)) return null
            val strings =
                when (val value = values[key]) {
                    is String -> splitHostString(value)
                    is Array<*> -> value.map { it as? String ?: throw ManagedConfigurationParseException(key) }
                    is ArrayList<*> -> value.map { it as? String ?: throw ManagedConfigurationParseException(key) }
                    is List<*> -> value.map { it as? String ?: throw ManagedConfigurationParseException(key) }
                    else -> throw ManagedConfigurationParseException(key)
                }
            return strings.mapNotNull(::normalizeHost).toSet()
        }

        private fun splitHostString(value: String): List<String> =
            value.split(',', '\n').map { it.trim() }

        private fun normalizeHost(host: String): String? {
            val trimmed = host.trim()
            return trimmed.ifEmpty { null }?.lowercase()
        }
    }
}

internal class ManagedConfigurationParseException(
    val key: String,
) : IllegalArgumentException("Invalid managed configuration value for $key.")

private val failClosedPolicy = localParseErrorPolicy()

private fun localParseErrorPolicy(): ProtocolV1Session.ManagedPolicy {
    val basePolicy = ProtocolV1Session.ManagedPolicy(
        isManaged = true,
        clipboardAllowed = false,
        fileTransferAllowed = false,
        audioAllowed = false,
        wakeAllowed = false,
        customGesturesAllowed = false,
        hostActionsAllowed = false,
        maximumFileBytes = 0L,
        allowedHosts = emptySet(),
        allowedHostsRestricted = true,
    )
    return basePolicy.copy(restrictionResults = parseErrorResults(basePolicy))
}

private fun parseErrorResults(policy: ProtocolV1Session.ManagedPolicy): List<ProtocolV1Session.RestrictionResult> =
    policy.restrictionResults.map { result ->
        result.copy(
            source = "local_parse_error",
            reason = result.reason.replace(
                "Local managed configuration result.",
                "Invalid local managed configuration; all product restrictions deny by default.",
            ),
        )
    }

private fun Bundle.toManagedConfigurationMap(): Map<String, Any?> =
    keySet().associateWith { key -> get(key) }
