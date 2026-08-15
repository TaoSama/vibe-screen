package dev.telemachus.display

import android.view.InputDevice
import android.view.KeyEvent
import android.view.MotionEvent
import java.security.MessageDigest
import kotlin.math.abs

internal const val CONTROLLER_BUTTON_COUNT = 13
internal const val CONTROLLER_BUTTON_MASK = (1 shl CONTROLLER_BUTTON_COUNT) - 1
internal const val MAXIMUM_ACTIVE_CONTROLLERS = 4

internal enum class ControllerEventKind { CONNECTED, STATE, DISCONNECTED }

internal enum class ControllerDelivery { ANALOG, STRUCTURAL }

internal enum class ControllerButton(val bit: Int) {
    A(0),
    B(1),
    X(2),
    Y(3),
    LEFT_SHOULDER(4),
    RIGHT_SHOULDER(5),
    LEFT_TRIGGER(6),
    RIGHT_TRIGGER(7),
    SELECT(8),
    START(9),
    MODE(10),
    LEFT_STICK(11),
    RIGHT_STICK(12),
}

internal enum class ControllerHatButton { LEFT, RIGHT, UP, DOWN }

internal data class ControllerAxisCalibration(
    val minimum: Float,
    val maximum: Float,
    val flat: Float,
) {
    init {
        require(minimum.isFinite() && maximum.isFinite() && flat.isFinite())
        require(minimum < maximum && flat >= 0f)
    }

    companion object {
        fun fromDeviceRange(minimum: Float, maximum: Float, flat: Float): ControllerAxisCalibration? {
            if (!minimum.isFinite() || !maximum.isFinite() || !flat.isFinite()) return null
            if (minimum >= maximum || flat < 0f) return null
            return ControllerAxisCalibration(minimum, maximum, flat)
        }
    }
}

internal data class ControllerAxes(
    val leftX: Double = 0.0,
    val leftY: Double = 0.0,
    val rightX: Double = 0.0,
    val rightY: Double = 0.0,
    val leftTrigger: Double = 0.0,
    val rightTrigger: Double = 0.0,
    val hatX: Int = 0,
    val hatY: Int = 0,
) {
    init {
        require(listOf(leftX, leftY, rightX, rightY).all { it.isFinite() && it in -1.0..1.0 })
        require(listOf(leftTrigger, rightTrigger).all { it.isFinite() && it in 0.0..1.0 })
        require(hatX in -1..1 && hatY in -1..1)
    }

    companion object {
        val NEUTRAL = ControllerAxes()
    }
}

internal data class ControllerStateSample(
    val controllerId: String,
    val controllerEpoch: Long,
    val kind: ControllerEventKind,
    val buttonMask: Int = 0,
    val axes: ControllerAxes = ControllerAxes.NEUTRAL,
) {
    init {
        val controllerIdBytes = controllerId.toByteArray(Charsets.UTF_8).size
        require(controllerIdBytes in 1..CONTROLLER_ID_MAX_UTF8_BYTES) {
            "controllerId must be 1..$CONTROLLER_ID_MAX_UTF8_BYTES UTF-8 bytes"
        }
        require(controllerEpoch > 0)
        require(buttonMask and CONTROLLER_BUTTON_MASK.inv() == 0)
        require(kind == ControllerEventKind.STATE || (buttonMask == 0 && axes == ControllerAxes.NEUTRAL))
    }

    companion object {
        internal const val CONTROLLER_ID_MAX_UTF8_BYTES = 128
    }
}

internal data class ControllerDispatch(
    val samples: List<ControllerStateSample>,
    val delivery: ControllerDelivery,
) {
    init {
        require(samples.isNotEmpty())
    }
}

internal data class ControllerMotionSnapshot(
    val controllerId: String,
    val frames: List<ControllerAxes>,
) {
    init {
        require(controllerId.isNotBlank() && frames.isNotEmpty())
    }
}

internal sealed interface ControllerKeyChange {
    val controllerId: String
    val pressed: Boolean

    data class Button(
        override val controllerId: String,
        override val pressed: Boolean,
        val button: ControllerButton,
    ) : ControllerKeyChange

    data class Hat(
        override val controllerId: String,
        override val pressed: Boolean,
        val direction: ControllerHatButton,
    ) : ControllerKeyChange
}

/** Pure normalization and canonical Android game-controller mapping. */
internal object ControllerInputMapper {
    fun normalizeStick(value: Float, calibration: ControllerAxisCalibration?): Double {
        if (!value.isFinite() || calibration == null) return 0.0
        val clamped = value.coerceIn(calibration.minimum, calibration.maximum)
        val flat = calibration.flat.coerceAtMost(maxOf(-calibration.minimum, calibration.maximum))
        if (abs(clamped) <= flat) return 0.0
        val normalized =
            if (clamped > 0f) {
                (clamped - flat) / (calibration.maximum - flat).coerceAtLeast(Float.MIN_VALUE)
            } else {
                (clamped + flat) / abs(calibration.minimum + flat).coerceAtLeast(Float.MIN_VALUE)
            }
        return normalized.toDouble().coerceIn(-1.0, 1.0)
    }

    fun normalizeTrigger(value: Float, calibration: ControllerAxisCalibration?): Double {
        if (!value.isFinite() || calibration == null) return 0.0
        val span = calibration.maximum - calibration.minimum
        if (span <= 0f) return 0.0
        val normalized = ((value.coerceIn(calibration.minimum, calibration.maximum) - calibration.minimum) / span)
        val normalizedFlat = (calibration.flat / span).coerceIn(0f, 1f)
        if (normalized <= normalizedFlat) return 0.0
        return ((normalized - normalizedFlat) / (1f - normalizedFlat).coerceAtLeast(Float.MIN_VALUE))
            .toDouble()
            .coerceIn(0.0, 1.0)
    }

    fun normalizeHat(value: Float, calibration: ControllerAxisCalibration?): Int {
        val normalized = normalizeStick(value, calibration)
        return when {
            normalized <= -HAT_THRESHOLD -> -1
            normalized >= HAT_THRESHOLD -> 1
            else -> 0
        }
    }

    fun stableControllerId(descriptor: String): String {
        require(descriptor.isNotBlank())
        val digest = MessageDigest.getInstance("SHA-256").digest(descriptor.toByteArray(Charsets.UTF_8))
        return "android-" +
            digest.take(CONTROLLER_ID_DIGEST_BYTES).joinToString("") { byte ->
                "%02x".format(byte.toInt() and 0xff)
            }
    }

    fun controllerId(device: InputDevice): String =
        stableControllerId(device.descriptor.ifBlank { fallbackDescriptor(device) })

    fun isControllerSource(source: Int): Boolean =
        source.hasSource(InputDevice.SOURCE_GAMEPAD) || source.hasSource(InputDevice.SOURCE_JOYSTICK)

    fun snapshot(event: MotionEvent): ControllerMotionSnapshot? {
        if (!isControllerSource(event.source) || event.actionMasked != MotionEvent.ACTION_MOVE) return null
        val device = event.device ?: return null
        val controllerId = controllerId(device)
        val frames =
            buildList {
                repeat(event.historySize) { historyPosition ->
                    add(readAxes(event, device, historyPosition))
                }
                add(readAxes(event, device, null))
            }
        return ControllerMotionSnapshot(controllerId, frames)
    }

    fun keyChange(event: KeyEvent): ControllerKeyChange? {
        if (!isControllerSource(event.source)) return null
        val pressed =
            when (event.action) {
                KeyEvent.ACTION_DOWN -> true
                KeyEvent.ACTION_UP -> false
                else -> return null
            }
        val device = event.device ?: return null
        val controllerId = controllerId(device)
        keyToButton(event.keyCode)?.let { return ControllerKeyChange.Button(controllerId, pressed, it) }
        keyToHat(event.keyCode)?.let { return ControllerKeyChange.Hat(controllerId, pressed, it) }
        return null
    }

    internal fun keyToButton(keyCode: Int): ControllerButton? =
        when (keyCode) {
            KeyEvent.KEYCODE_BUTTON_A -> ControllerButton.A
            KeyEvent.KEYCODE_BUTTON_B -> ControllerButton.B
            KeyEvent.KEYCODE_BUTTON_X -> ControllerButton.X
            KeyEvent.KEYCODE_BUTTON_Y -> ControllerButton.Y
            KeyEvent.KEYCODE_BUTTON_L1 -> ControllerButton.LEFT_SHOULDER
            KeyEvent.KEYCODE_BUTTON_R1 -> ControllerButton.RIGHT_SHOULDER
            KeyEvent.KEYCODE_BUTTON_L2 -> ControllerButton.LEFT_TRIGGER
            KeyEvent.KEYCODE_BUTTON_R2 -> ControllerButton.RIGHT_TRIGGER
            KeyEvent.KEYCODE_BUTTON_THUMBL -> ControllerButton.LEFT_STICK
            KeyEvent.KEYCODE_BUTTON_THUMBR -> ControllerButton.RIGHT_STICK
            KeyEvent.KEYCODE_BUTTON_START -> ControllerButton.START
            KeyEvent.KEYCODE_BUTTON_SELECT -> ControllerButton.SELECT
            KeyEvent.KEYCODE_BUTTON_MODE -> ControllerButton.MODE
            else -> null
        }

    internal fun keyToHat(keyCode: Int): ControllerHatButton? =
        when (keyCode) {
            KeyEvent.KEYCODE_DPAD_LEFT -> ControllerHatButton.LEFT
            KeyEvent.KEYCODE_DPAD_RIGHT -> ControllerHatButton.RIGHT
            KeyEvent.KEYCODE_DPAD_UP -> ControllerHatButton.UP
            KeyEvent.KEYCODE_DPAD_DOWN -> ControllerHatButton.DOWN
            else -> null
        }

    private fun readAxes(event: MotionEvent, device: InputDevice, historyPosition: Int?): ControllerAxes {
        fun calibration(axis: Int): ControllerAxisCalibration? =
            device.getMotionRange(axis, event.source)?.toCalibration()
                ?: device.getMotionRange(axis)?.toCalibration()

        fun value(axis: Int): Float =
            historyPosition?.let { event.getHistoricalAxisValue(axis, it) } ?: event.getAxisValue(axis)

        fun trigger(primary: Int, fallback: Int): Double {
            val primaryCalibration = calibration(primary)
            return if (primaryCalibration != null) {
                normalizeTrigger(value(primary), primaryCalibration)
            } else {
                normalizeTrigger(value(fallback), calibration(fallback))
            }
        }

        return ControllerAxes(
            leftX = normalizeStick(value(MotionEvent.AXIS_X), calibration(MotionEvent.AXIS_X)),
            leftY = normalizeStick(value(MotionEvent.AXIS_Y), calibration(MotionEvent.AXIS_Y)),
            rightX = normalizeStick(value(MotionEvent.AXIS_Z), calibration(MotionEvent.AXIS_Z)),
            rightY = normalizeStick(value(MotionEvent.AXIS_RZ), calibration(MotionEvent.AXIS_RZ)),
            leftTrigger = trigger(MotionEvent.AXIS_LTRIGGER, MotionEvent.AXIS_BRAKE),
            rightTrigger = trigger(MotionEvent.AXIS_RTRIGGER, MotionEvent.AXIS_GAS),
            hatX = normalizeHat(value(MotionEvent.AXIS_HAT_X), calibration(MotionEvent.AXIS_HAT_X)),
            hatY = normalizeHat(value(MotionEvent.AXIS_HAT_Y), calibration(MotionEvent.AXIS_HAT_Y)),
        )
    }

    private fun InputDevice.MotionRange.toCalibration() =
        ControllerAxisCalibration.fromDeviceRange(min, max, flat)

    private fun fallbackDescriptor(device: InputDevice): String =
        "${device.vendorId}:${device.productId}:${device.name}:${device.sources}"

    private fun Int.hasSource(expected: Int): Boolean = this and expected == expected

    private const val HAT_THRESHOLD = 0.5
    private const val CONTROLLER_ID_DIGEST_BYTES = 12
}

/** Owns controller attachment epochs and complete state snapshots for one client process. */
internal class ControllerSessionState {
    private val lock = Any()
    private val lastEpochs = mutableMapOf<String, Long>()
    private val active = linkedMapOf<String, ActiveController>()

    fun connect(controllerId: String): ControllerDispatch? = synchronized(lock) {
        if (controllerId in active) return@synchronized null
        val controller = attach(controllerId) ?: return@synchronized null
        ControllerDispatch(
            listOf(controller.lifecycle(ControllerEventKind.CONNECTED)) + fullStateSnapshots(),
            ControllerDelivery.STRUCTURAL,
        )
    }

    fun applyMotion(snapshot: ControllerMotionSnapshot): ControllerDispatch? = synchronized(lock) {
        val samples = mutableListOf<ControllerStateSample>()
        val controller =
            active[snapshot.controllerId]
                ?: attach(snapshot.controllerId)?.also {
                    samples += it.lifecycle(ControllerEventKind.CONNECTED)
                }
                ?: return@synchronized null
        var structural = samples.isNotEmpty()
        snapshot.frames.forEach { axes ->
            val previous = controller.currentAxes()
            controller.motionAxes = axes
            val current = controller.currentAxes()
            if (previous.hatX != current.hatX || previous.hatY != current.hatY) structural = true
            samples += fullStateSnapshots()
        }
        ControllerDispatch(
            samples = samples,
            delivery = if (structural) ControllerDelivery.STRUCTURAL else ControllerDelivery.ANALOG,
        )
    }

    fun applyKey(change: ControllerKeyChange): ControllerDispatch? = synchronized(lock) {
        val samples = mutableListOf<ControllerStateSample>()
        val controller =
            active[change.controllerId]
                ?: attach(change.controllerId)?.also {
                    samples += it.lifecycle(ControllerEventKind.CONNECTED)
                }
                ?: return@synchronized null
        val changed =
            when (change) {
                is ControllerKeyChange.Button -> {
                    val previous = controller.buttonMask
                    val bit = 1 shl change.button.bit
                    controller.buttonMask =
                        if (change.pressed) controller.buttonMask or bit else controller.buttonMask and bit.inv()
                    previous != controller.buttonMask
                }

                is ControllerKeyChange.Hat -> {
                    val previous = controller.currentAxes()
                    if (change.pressed) controller.pressedHat += change.direction else controller.pressedHat -= change.direction
                    previous != controller.currentAxes()
                }
            }
        if (changed || samples.isNotEmpty()) samples += fullStateSnapshots()
        if (samples.isEmpty()) null else ControllerDispatch(samples, ControllerDelivery.STRUCTURAL)
    }

    fun disconnect(controllerId: String): ControllerDispatch? = synchronized(lock) {
        val controller = active.remove(controllerId) ?: return@synchronized null
        ControllerDispatch(
            controller.releaseSamples() + fullStateSnapshots(),
            ControllerDelivery.STRUCTURAL,
        )
    }

    fun takeRelease(): ControllerDispatch? = synchronized(lock) {
        if (active.isEmpty()) return@synchronized null
        val samples = active.values.sortedBy { it.controllerId }.flatMap { it.releaseSamples() }
        active.clear()
        ControllerDispatch(samples, ControllerDelivery.STRUCTURAL)
    }

    /** Drops unsent active state after transport loss while preserving this session's epoch history. */
    fun discardActiveForTransportLoss() = synchronized(lock) {
        active.clear()
    }

    /** Resets all controller epochs and active state for a newly negotiated session. */
    fun resetForNewSession() = synchronized(lock) {
        active.clear()
        lastEpochs.clear()
    }

    internal fun activeSnapshots(): List<ControllerStateSample> = synchronized(lock) { fullStateSnapshots() }

    private fun attach(controllerId: String): ActiveController? {
        require(controllerId.isNotBlank())
        if (active.size >= MAXIMUM_ACTIVE_CONTROLLERS) return null
        val previousEpoch = lastEpochs[controllerId] ?: 0L
        check(previousEpoch < Long.MAX_VALUE) { "Controller epoch exhausted" }
        return ActiveController(controllerId, previousEpoch + 1).also {
            lastEpochs[controllerId] = it.epoch
            active[controllerId] = it
        }
    }

    private fun fullStateSnapshots(): List<ControllerStateSample> =
        active.values.sortedBy { it.controllerId }.map(ActiveController::state)

    private data class ActiveController(
        val controllerId: String,
        val epoch: Long,
        var buttonMask: Int = 0,
        var motionAxes: ControllerAxes = ControllerAxes.NEUTRAL,
        val pressedHat: MutableSet<ControllerHatButton> = mutableSetOf(),
    ) {
        fun lifecycle(kind: ControllerEventKind) = ControllerStateSample(controllerId, epoch, kind)

        fun state() = ControllerStateSample(controllerId, epoch, ControllerEventKind.STATE, buttonMask, currentAxes())

        fun releaseSamples() =
            listOf(
                ControllerStateSample(controllerId, epoch, ControllerEventKind.STATE),
                lifecycle(ControllerEventKind.DISCONNECTED),
            )

        fun keyHatX(): Int =
            ((if (ControllerHatButton.RIGHT in pressedHat) 1 else 0) -
                (if (ControllerHatButton.LEFT in pressedHat) 1 else 0)).coerceIn(-1, 1)

        fun keyHatY(): Int =
            ((if (ControllerHatButton.DOWN in pressedHat) 1 else 0) -
                (if (ControllerHatButton.UP in pressedHat) 1 else 0)).coerceIn(-1, 1)

        fun currentAxes(): ControllerAxes {
            val keyX = keyHatX()
            val keyY = keyHatY()
            return motionAxes.copy(
                hatX =
                    if (ControllerHatButton.LEFT in pressedHat || ControllerHatButton.RIGHT in pressedHat) {
                        keyX
                    } else {
                        motionAxes.hatX
                    },
                hatY =
                    if (ControllerHatButton.UP in pressedHat || ControllerHatButton.DOWN in pressedHat) {
                        keyY
                    } else {
                        motionAxes.hatY
                    },
            )
        }
    }
}
