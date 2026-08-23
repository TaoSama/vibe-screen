package dev.telemachus.display

internal enum class ClientPointerAction {
    MOVE,
    BUTTON_PRESS,
    BUTTON_RELEASE,
    SCROLL,
}

internal data class ClientPointerInput(
    val action: ClientPointerAction,
    val x: Float,
    val y: Float,
    val buttonState: Int = 0,
    val actionButton: Int = 0,
    val horizontalScroll: Float = 0f,
    val verticalScroll: Float = 0f,
)

internal data class ClientControllerInput(
    val dispatch: ControllerDispatch,
)

internal data class ClientPeripheralInput(
    val peripheralKind: String,
    val payload: ByteArray,
)

internal interface ClientSessionInputSink {
    fun sendKey(input: ClientKeyInput): Boolean

    fun sendPointer(input: ClientPointerInput): Boolean

    fun sendController(input: ClientControllerInput): Boolean

    fun sendPeripheral(input: ClientPeripheralInput): Boolean
}

internal data class ClientSessionBinding(
    val capabilities: ClientSessionCapabilities,
    val inputSink: ClientSessionInputSink? = null,
) {
    init {
        require(!capabilities.keyboard || inputSink != null) {
            "Keyboard capability requires a session input sink"
        }
        require(!capabilities.nativePointer || inputSink != null) {
            "Native pointer capability requires a session input sink"
        }
        require(!capabilities.controller || inputSink != null) {
            "Controller capability requires a session input sink"
        }
        require(!capabilities.peripheralInputFramework || inputSink != null) {
            "Peripheral input framework capability requires a session input sink"
        }
    }

    companion object {
        val LEGACY_TOUCH_ONLY = ClientSessionBinding(ClientSessionCapabilities.LEGACY_TOUCH_ONLY)
    }
}

internal enum class ClientInputDispatchResult {
    UNSUPPORTED,
    SENT,
    REJECTED,
}

internal class ClientInputDispatch(
    private val binding: ClientSessionBinding,
) {
    fun sendKey(input: ClientKeyInput): ClientInputDispatchResult {
        if (!binding.capabilities.keyboard) return ClientInputDispatchResult.UNSUPPORTED
        return binding.inputSink.send { sendKey(input) }
    }

    fun sendPointer(input: ClientPointerInput): ClientInputDispatchResult {
        if (!binding.capabilities.nativePointer) return ClientInputDispatchResult.UNSUPPORTED
        return binding.inputSink.send { sendPointer(input) }
    }

    fun sendController(input: ClientControllerInput): ClientInputDispatchResult {
        if (!binding.capabilities.controller) return ClientInputDispatchResult.UNSUPPORTED
        return binding.inputSink.send { sendController(input) }
    }

    fun sendPeripheral(input: ClientPeripheralInput): ClientInputDispatchResult {
        if (!binding.capabilities.peripheralInputFramework) return ClientInputDispatchResult.UNSUPPORTED
        return binding.inputSink.send { sendPeripheral(input) }
    }

    private fun ClientSessionInputSink?.send(block: ClientSessionInputSink.() -> Boolean): ClientInputDispatchResult =
        if (this != null && block()) ClientInputDispatchResult.SENT else ClientInputDispatchResult.REJECTED
}
