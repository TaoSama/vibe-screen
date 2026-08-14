package dev.telemachus.display

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import androidx.annotation.RequiresApi
import androidx.core.content.ContextCompat

internal enum class DeviceThermalState {
    UNKNOWN,
    NOMINAL,
    ELEVATED,
    SEVERE,
    CRITICAL,
}

internal data class DeviceHealthSnapshot(
    val batteryPercent: Int? = null,
    val charging: Boolean? = null,
    val powerSaveMode: Boolean = false,
    val thermalState: DeviceThermalState = DeviceThermalState.UNKNOWN,
)

internal enum class DeviceHealthAttention {
    UNKNOWN,
    NORMAL,
    POWER_RECOMMENDED,
    THERMAL_ELEVATED,
    THERMAL_HIGH,
}

internal object DeviceHealthPolicy {
    fun batteryPercent(level: Int, scale: Int): Int? =
        if (level < 0 || scale <= 0) null else ((level * 100.0) / scale).toInt().coerceIn(0, 100)

    fun isCharging(status: Int): Boolean? =
        when (status) {
            BatteryManager.BATTERY_STATUS_CHARGING,
            BatteryManager.BATTERY_STATUS_FULL,
            -> true

            BatteryManager.BATTERY_STATUS_DISCHARGING,
            BatteryManager.BATTERY_STATUS_NOT_CHARGING,
            -> false

            else -> null
        }

    fun thermalState(status: Int?): DeviceThermalState =
        when {
            status == null -> DeviceThermalState.UNKNOWN
            status >= PowerManager.THERMAL_STATUS_CRITICAL -> DeviceThermalState.CRITICAL
            status >= PowerManager.THERMAL_STATUS_SEVERE -> DeviceThermalState.SEVERE
            status >= PowerManager.THERMAL_STATUS_LIGHT -> DeviceThermalState.ELEVATED
            status == PowerManager.THERMAL_STATUS_NONE -> DeviceThermalState.NOMINAL
            else -> DeviceThermalState.UNKNOWN
        }

    fun attention(snapshot: DeviceHealthSnapshot): DeviceHealthAttention =
        when (snapshot.thermalState) {
            DeviceThermalState.CRITICAL,
            DeviceThermalState.SEVERE,
            -> DeviceHealthAttention.THERMAL_HIGH

            DeviceThermalState.ELEVATED -> DeviceHealthAttention.THERMAL_ELEVATED
            else ->
                if (snapshot.batteryPercent == null && snapshot.charging == null) {
                    DeviceHealthAttention.UNKNOWN
                } else if (snapshot.charging == false && (snapshot.batteryPercent ?: 100) <= LOW_BATTERY_PERCENT) {
                    DeviceHealthAttention.POWER_RECOMMENDED
                } else {
                    DeviceHealthAttention.NORMAL
                }
        }

    private const val LOW_BATTERY_PERCENT = 20
}

/** Drops duplicate and late platform callbacks outside the visible Activity lifecycle. */
internal class DeviceHealthLifecycle {
    private var active = false
    private var generation = 0L
    private var current = DeviceHealthSnapshot()

    @Synchronized
    fun start(): Long {
        generation += 1
        active = true
        return generation
    }

    @Synchronized
    fun stop() {
        active = false
    }

    @Synchronized
    fun publish(
        callbackGeneration: Long,
        snapshot: DeviceHealthSnapshot,
    ): DeviceHealthSnapshot? {
        if (!active || callbackGeneration != generation || snapshot == current) return null
        current = snapshot
        return snapshot
    }

    @Synchronized
    fun snapshot(): DeviceHealthSnapshot = current

    @Synchronized
    fun accepts(callbackGeneration: Long): Boolean = active && callbackGeneration == generation
}

/** Foreground-only battery, power-saver, and thermal observation for sustained tablet use. */
internal class AndroidDeviceHealthMonitor(
    context: Context,
    private val onChanged: (DeviceHealthSnapshot) -> Unit,
    private val onError: (Throwable) -> Unit,
) {
    private val applicationContext = context.applicationContext
    private val powerManager = applicationContext.getSystemService(PowerManager::class.java)
    private val lifecycle = DeviceHealthLifecycle()
    private val mainHandler = Handler(Looper.getMainLooper())
    private var started = false
    private var receiver: BroadcastReceiver? = null
    private var thermalObserver: ThermalObserver? = null

    fun start() {
        if (started) return
        started = true
        val generation = lifecycle.start()
        val batteryIntent =
            runCatching {
                applicationContext.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
            }.onFailure(onError).getOrNull()
        runCatching {
            val generationReceiver =
                object : BroadcastReceiver() {
                    override fun onReceive(context: Context, intent: Intent) {
                        refresh(generation, intent.takeIf { it.action == Intent.ACTION_BATTERY_CHANGED })
                    }
                }
            val filter =
                IntentFilter().apply {
                    addAction(Intent.ACTION_BATTERY_CHANGED)
                    addAction(PowerManager.ACTION_POWER_SAVE_MODE_CHANGED)
                }
            ContextCompat.registerReceiver(
                applicationContext,
                generationReceiver,
                filter,
                ContextCompat.RECEIVER_EXPORTED,
            )
            receiver = generationReceiver
        }.onFailure(onError)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            runCatching {
                Api29ThermalObserver(
                    powerManager = powerManager,
                    dispatch = { command ->
                        mainHandler.post {
                            if (lifecycle.accepts(generation)) command.run()
                        }
                    },
                    onChanged = { status ->
                        publish(
                            generation,
                            lifecycle.snapshot().copy(thermalState = DeviceHealthPolicy.thermalState(status)),
                        )
                    },
                ).also {
                    it.start()
                    thermalObserver = it
                }
            }.onFailure(onError)
        }
        refresh(generation, batteryIntent)
    }

    fun stop() {
        if (!started) return
        started = false
        lifecycle.stop()
        receiver?.let { registeredReceiver ->
            runCatching { applicationContext.unregisterReceiver(registeredReceiver) }.onFailure(onError)
        }
        receiver = null
        thermalObserver?.let { observer -> runCatching(observer::stop).onFailure(onError) }
        thermalObserver = null
    }

    fun snapshot(): DeviceHealthSnapshot = lifecycle.snapshot()

    private fun readSnapshot(batteryIntent: Intent?): DeviceHealthSnapshot {
        val previous = lifecycle.snapshot()
        val status = batteryIntent?.getIntExtra(BatteryManager.EXTRA_STATUS, BatteryManager.BATTERY_STATUS_UNKNOWN)
        val thermal =
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                DeviceHealthPolicy.thermalState(powerManager.currentThermalStatus)
            } else {
                DeviceThermalState.UNKNOWN
            }
        return previous.copy(
            batteryPercent =
                batteryIntent?.let {
                    DeviceHealthPolicy.batteryPercent(
                        it.getIntExtra(BatteryManager.EXTRA_LEVEL, -1),
                        it.getIntExtra(BatteryManager.EXTRA_SCALE, -1),
                    )
                } ?: previous.batteryPercent,
            charging = status?.let(DeviceHealthPolicy::isCharging) ?: previous.charging,
            powerSaveMode = powerManager.isPowerSaveMode,
            thermalState = thermal,
        )
    }

    private fun publish(
        generation: Long,
        snapshot: DeviceHealthSnapshot,
    ) {
        lifecycle.publish(generation, snapshot)?.let(onChanged)
    }

    private fun refresh(
        generation: Long,
        batteryIntent: Intent?,
    ) {
        runCatching { readSnapshot(batteryIntent) }
            .onSuccess { snapshot -> publish(generation, snapshot) }
            .onFailure(onError)
    }

    private interface ThermalObserver {
        fun stop()
    }

    @RequiresApi(Build.VERSION_CODES.Q)
    private class Api29ThermalObserver(
        private val powerManager: PowerManager,
        private val dispatch: java.util.concurrent.Executor,
        onChanged: (Int) -> Unit,
    ) : ThermalObserver {
        private val listener = PowerManager.OnThermalStatusChangedListener(onChanged)

        fun start() {
            powerManager.addThermalStatusListener(dispatch, listener)
        }

        override fun stop() {
            powerManager.removeThermalStatusListener(listener)
        }
    }
}
