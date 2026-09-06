package dev.telemachus.display

import java.util.Locale

internal enum class PeripheralInputDiagnosticKind(val wireName: String) {
    NATIVE_POINTER_UNNEGOTIATED("native_pointer_unnegotiated"),
    NATIVE_POINTER_SINK_REJECTED("native_pointer_sink_rejected"),
    NATIVE_POINTER_FORWARDED("native_pointer_forwarded"),
    CONTROLLER_UNNEGOTIATED("controller_unnegotiated"),
    CONTROLLER_SINK_REJECTED("controller_sink_rejected"),
    CONTROLLER_HOTPLUG_SYNCHRONIZED("controller_hotplug_synchronized"),
    CONTROLLER_LIMIT_REACHED("controller_limit_reached"),
    CONTROLLER_HOST_REJECTED("controller_host_rejected"),
    UNSUPPORTED_PERIPHERAL_KIND("unsupported_peripheral_kind"),
}

internal enum class PeripheralInputDiagnosticTransport(val wireName: String) {
    USB_LAN("usb_lan"),
    INTERNET("internet"),
}

internal data class PeripheralInputDiagnostic(
    val kind: PeripheralInputDiagnosticKind,
    val fields: Map<String, String>,
) {
    fun message(): String =
        buildString {
            append(PERIPHERAL_INPUT_DIAGNOSTIC_PREFIX)
            append(" kind=")
            append(kind.wireName)
            fields.forEach { (key, value) ->
                append(' ')
                append(key)
                append('=')
                append(value)
            }
            append(" acceptance_evidence=")
            append(EXTERNAL_ACCEPTANCE_EVIDENCE_REQUIRED)
        }
}

internal object PeripheralInputDiagnostics {
    fun nativePointerUnsupported(
        input: ClientPointerInput,
        capabilities: ClientSessionCapabilities,
    ): PeripheralInputDiagnostic =
        diagnostic(
            PeripheralInputDiagnosticKind.NATIVE_POINTER_UNNEGOTIATED,
            FIELD_TRANSPORT to PeripheralInputDiagnosticTransport.USB_LAN.wireName,
            FIELD_CAPABILITY to "native_pointer",
            FIELD_NEGOTIATED to capabilities.nativePointer,
            FIELD_TOUCH_ONLY to (capabilities == ClientSessionCapabilities.LEGACY_TOUCH_ONLY),
            FIELD_ACTION to input.action,
            FIELD_BUTTON_STATE to input.buttonState,
            FIELD_ACTION_BUTTON to input.actionButton,
        )

    fun nativePointerSinkRejected(input: ClientPointerInput): PeripheralInputDiagnostic =
        diagnostic(
            PeripheralInputDiagnosticKind.NATIVE_POINTER_SINK_REJECTED,
            FIELD_TRANSPORT to PeripheralInputDiagnosticTransport.USB_LAN.wireName,
            FIELD_ACTION to input.action,
            FIELD_BUTTON_STATE to input.buttonState,
            FIELD_ACTION_BUTTON to input.actionButton,
        )

    fun nativePointerForwarded(
        eventDeviceId: Int,
        eventSource: Int,
        inputDeviceSources: Int?,
        eventButtonState: Int,
        eventActionButton: Int,
        input: ClientPointerInput,
    ): PeripheralInputDiagnostic =
        diagnostic(
            PeripheralInputDiagnosticKind.NATIVE_POINTER_FORWARDED,
            FIELD_TRANSPORT to PeripheralInputDiagnosticTransport.USB_LAN.wireName,
            FIELD_ACTION to input.action,
            FIELD_DEVICE_ID to eventDeviceId,
            FIELD_SOURCES to sourceNames(eventSource, inputDeviceSources),
            FIELD_BUTTON_STATE to eventButtonState,
            FIELD_ACTION_BUTTON to eventActionButton,
            FIELD_WIRE_BUTTONS to NativeInputWire.buttonMask(eventButtonState),
            FIELD_X to input.x,
            FIELD_Y to input.y,
        )

    fun controllerCapabilityUnsupported(
        transport: PeripheralInputDiagnosticTransport,
        source: String,
    ): PeripheralInputDiagnostic =
        diagnostic(
            PeripheralInputDiagnosticKind.CONTROLLER_UNNEGOTIATED,
            FIELD_TRANSPORT to transport.wireName,
            FIELD_CAPABILITY to "controller",
            FIELD_NEGOTIATED to false,
            FIELD_SOURCE to source,
        )

    fun controllerSinkRejected(
        transport: PeripheralInputDiagnosticTransport,
        source: String,
    ): PeripheralInputDiagnostic =
        diagnostic(
            PeripheralInputDiagnosticKind.CONTROLLER_SINK_REJECTED,
            FIELD_TRANSPORT to transport.wireName,
            FIELD_SOURCE to source,
        )

    fun controllerHotplugSynchronized(
        reason: String,
        availableDeviceCount: Int,
        result: ControllerHotplugSyncResult,
    ): PeripheralInputDiagnostic =
        diagnostic(
            PeripheralInputDiagnosticKind.CONTROLLER_HOTPLUG_SYNCHRONIZED,
            FIELD_TRANSPORT to PeripheralInputDiagnosticTransport.USB_LAN.wireName,
            FIELD_REASON to reason,
            FIELD_AVAILABLE_DEVICES to availableDeviceCount,
            FIELD_CONNECTED to result.connected,
            FIELD_DISCONNECTED to result.disconnected,
            FIELD_RESYNCHRONIZED to result.resynchronized,
            FIELD_LIMIT_REACHED to result.limitReached,
        )

    fun controllerLimitReached(
        reason: String,
        availableDeviceCount: Int,
        limitReached: Int,
    ): PeripheralInputDiagnostic =
        diagnostic(
            PeripheralInputDiagnosticKind.CONTROLLER_LIMIT_REACHED,
            FIELD_TRANSPORT to PeripheralInputDiagnosticTransport.USB_LAN.wireName,
            FIELD_REASON to reason,
            FIELD_AVAILABLE_DEVICES to availableDeviceCount,
            FIELD_LIMIT_REACHED to limitReached,
            FIELD_ACTIVE_LIMIT to MAXIMUM_ACTIVE_CONTROLLERS,
            FIELD_REJECTION_REASON to MAXIMUM_ACTIVE_CONTROLLERS_REJECTION_REASON,
        )

    fun controllerHostRejected(
        transport: PeripheralInputDiagnosticTransport,
        controllerId: String,
        controllerEpoch: Long,
        rejectionReason: String?,
        inputId: Long? = null,
    ): PeripheralInputDiagnostic {
        val fields =
            buildList {
                add(FIELD_TRANSPORT to transport.wireName)
                inputId?.let { add(FIELD_INPUT_ID to it) }
                add(FIELD_CONTROLLER_ID to controllerId)
                add(FIELD_CONTROLLER_EPOCH to controllerEpoch)
                add(FIELD_REJECTION_REASON to stableValue(rejectionReason))
            }
        return diagnostic(PeripheralInputDiagnosticKind.CONTROLLER_HOST_REJECTED, fields)
    }

    fun unsupportedPeripheralKind(
        peripheralKind: String,
        rejectionReason: String = UNSUPPORTED_PERIPHERAL_KIND_REJECTION_REASON,
    ): PeripheralInputDiagnostic =
        diagnostic(
            PeripheralInputDiagnosticKind.UNSUPPORTED_PERIPHERAL_KIND,
            FIELD_CAPABILITY to "peripheral_input_framework",
            FIELD_PERIPHERAL_KIND to peripheralKind,
            FIELD_REJECTION_REASON to rejectionReason,
        )

    private fun diagnostic(
        kind: PeripheralInputDiagnosticKind,
        vararg fields: Pair<String, Any?>,
    ): PeripheralInputDiagnostic = diagnostic(kind, fields.toList())

    private fun diagnostic(
        kind: PeripheralInputDiagnosticKind,
        fields: List<Pair<String, Any?>>,
    ): PeripheralInputDiagnostic =
        PeripheralInputDiagnostic(
            kind = kind,
            fields = fields.associateTo(LinkedHashMap()) { (key, value) -> key to stableValue(value) },
        )

    private fun sourceNames(
        eventSource: Int,
        inputDeviceSources: Int?,
    ): String =
        NativeInputWire
            .mouseLikeSourceNames(eventSource, inputDeviceSources)
            .joinToString("+")
            .ifEmpty { FALLBACK_SOURCE }

    private fun stableValue(value: Any?): String {
        val raw =
            when (value) {
                null -> ""
                is Float -> value.toStableString()
                is Double -> value.toFloat().toStableString()
                is Boolean -> value.toString()
                is Number -> value.toString()
                is Enum<*> -> value.name.lowercase(Locale.US)
                else -> value.toString()
            }.trim()
        if (raw.isEmpty()) return UNSPECIFIED_VALUE
        return UNSAFE_FIELD_VALUE.replace(raw.replace(WHITESPACE, "_"), "_")
    }

    private fun Float.toStableString(): String =
        if (isFinite()) {
            String.format(Locale.US, "%.3f", this).trimEnd('0').trimEnd('.')
        } else {
            UNSPECIFIED_VALUE
        }
}

internal const val UNSUPPORTED_PERIPHERAL_KIND_REJECTION_REASON = "unsupported_peripheral_kind"

private const val PERIPHERAL_INPUT_DIAGNOSTIC_PREFIX = "peripheral_input"
private const val EXTERNAL_ACCEPTANCE_EVIDENCE_REQUIRED = "external_gate_required"
private const val UNSPECIFIED_VALUE = "unspecified"
private const val FALLBACK_SOURCE = "OTHER"

private const val FIELD_TRANSPORT = "transport"
private const val FIELD_CAPABILITY = "capability"
private const val FIELD_NEGOTIATED = "negotiated"
private const val FIELD_TOUCH_ONLY = "touch_only"
private const val FIELD_ACTION = "action"
private const val FIELD_BUTTON_STATE = "button_state"
private const val FIELD_ACTION_BUTTON = "action_button"
private const val FIELD_DEVICE_ID = "device_id"
private const val FIELD_SOURCES = "sources"
private const val FIELD_WIRE_BUTTONS = "wire_buttons"
private const val FIELD_X = "x"
private const val FIELD_Y = "y"
private const val FIELD_SOURCE = "source"
private const val FIELD_REASON = "reason"
private const val FIELD_AVAILABLE_DEVICES = "available_devices"
private const val FIELD_CONNECTED = "connected"
private const val FIELD_DISCONNECTED = "disconnected"
private const val FIELD_RESYNCHRONIZED = "resynchronized"
private const val FIELD_LIMIT_REACHED = "limit_reached"
private const val FIELD_ACTIVE_LIMIT = "active_limit"
private const val FIELD_CONTROLLER_ID = "controller_id"
private const val FIELD_CONTROLLER_EPOCH = "controller_epoch"
private const val FIELD_INPUT_ID = "input_id"
private const val FIELD_REJECTION_REASON = "rejection_reason"
private const val FIELD_PERIPHERAL_KIND = "peripheral_kind"

private val WHITESPACE = Regex("\\s+")
private val UNSAFE_FIELD_VALUE = Regex("[^A-Za-z0-9_./:+-]")
