package dev.telemachus.display

import android.os.BatteryManager
import android.os.PowerManager
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class DeviceHealthMonitorTest {
    @Test
    fun `battery values are bounded and unknown inputs stay unknown`() {
        assertEquals(50, DeviceHealthPolicy.batteryPercent(1, 2))
        assertEquals(100, DeviceHealthPolicy.batteryPercent(12, 10))
        assertNull(DeviceHealthPolicy.batteryPercent(-1, 100))
        assertNull(DeviceHealthPolicy.batteryPercent(40, 0))
        assertEquals(true, DeviceHealthPolicy.isCharging(BatteryManager.BATTERY_STATUS_CHARGING))
        assertEquals(true, DeviceHealthPolicy.isCharging(BatteryManager.BATTERY_STATUS_FULL))
        assertEquals(false, DeviceHealthPolicy.isCharging(BatteryManager.BATTERY_STATUS_DISCHARGING))
        assertEquals(false, DeviceHealthPolicy.isCharging(BatteryManager.BATTERY_STATUS_NOT_CHARGING))
        assertNull(DeviceHealthPolicy.isCharging(BatteryManager.BATTERY_STATUS_UNKNOWN))
    }

    @Test
    fun `thermal severity takes priority over low battery guidance`() {
        assertEquals(DeviceHealthAttention.UNKNOWN, DeviceHealthPolicy.attention(DeviceHealthSnapshot()))
        assertEquals(
            DeviceHealthAttention.POWER_SAVER,
            DeviceHealthPolicy.attention(DeviceHealthSnapshot(90, charging = true, powerSaveMode = true)),
        )
        assertEquals(
            DeviceHealthAttention.POWER_SAVER,
            DeviceHealthPolicy.attention(DeviceHealthSnapshot(powerSaveMode = true)),
        )
        assertEquals(
            DeviceHealthAttention.POWER_RECOMMENDED,
            DeviceHealthPolicy.attention(DeviceHealthSnapshot(20, charging = false)),
        )
        assertEquals(
            DeviceHealthAttention.POWER_RECOMMENDED,
            DeviceHealthPolicy.attention(DeviceHealthSnapshot(10, charging = null)),
        )
        assertEquals(
            DeviceHealthAttention.NORMAL,
            DeviceHealthPolicy.attention(DeviceHealthSnapshot(10, charging = true)),
        )
        assertEquals(
            DeviceHealthAttention.NORMAL,
            DeviceHealthPolicy.attention(DeviceHealthSnapshot(null, charging = false)),
        )
        assertEquals(
            DeviceHealthAttention.NORMAL,
            DeviceHealthPolicy.attention(DeviceHealthSnapshot(21, charging = false)),
        )
        assertEquals(
            DeviceHealthAttention.THERMAL_ELEVATED,
            DeviceHealthPolicy.attention(
                DeviceHealthSnapshot(10, charging = false, powerSaveMode = true, thermalState = DeviceThermalState.ELEVATED),
            ),
        )
        assertEquals(
            DeviceHealthAttention.THERMAL_HIGH,
            DeviceHealthPolicy.attention(DeviceHealthSnapshot(90, charging = true, thermalState = DeviceThermalState.SEVERE)),
        )
        assertEquals(DeviceThermalState.CRITICAL, DeviceHealthPolicy.thermalState(PowerManager.THERMAL_STATUS_SHUTDOWN))
        assertEquals(DeviceThermalState.UNKNOWN, DeviceHealthPolicy.thermalState(null))
        assertEquals(DeviceThermalState.NOMINAL, DeviceHealthPolicy.thermalState(PowerManager.THERMAL_STATUS_NONE))
        assertEquals(DeviceThermalState.ELEVATED, DeviceHealthPolicy.thermalState(PowerManager.THERMAL_STATUS_LIGHT))
        assertEquals(DeviceThermalState.ELEVATED, DeviceHealthPolicy.thermalState(PowerManager.THERMAL_STATUS_MODERATE))
        assertEquals(DeviceThermalState.SEVERE, DeviceHealthPolicy.thermalState(PowerManager.THERMAL_STATUS_SEVERE))
        assertEquals(DeviceThermalState.CRITICAL, DeviceHealthPolicy.thermalState(PowerManager.THERMAL_STATUS_CRITICAL))
    }

    @Test
    fun `lifecycle emits changes once and rejects callbacks after stop`() {
        val lifecycle = DeviceHealthLifecycle()
        val changed = DeviceHealthSnapshot(72, charging = true, thermalState = DeviceThermalState.NOMINAL)

        assertNull(lifecycle.publish(0, changed))
        val generation = lifecycle.start()
        assertTrue(lifecycle.accepts(generation))
        assertEquals(changed, lifecycle.publish(generation, changed))
        assertNull(lifecycle.publish(generation, changed))
        lifecycle.stop()
        assertFalse(lifecycle.accepts(generation))
        assertNull(lifecycle.publish(generation, changed.copy(batteryPercent = 71)))
        assertEquals(changed, lifecycle.snapshot())
    }

    @Test
    fun `callback queued before stop cannot publish into restarted generation`() {
        val lifecycle = DeviceHealthLifecycle()
        val firstGeneration = lifecycle.start()
        val firstSnapshot = DeviceHealthSnapshot(80, charging = true)
        assertEquals(firstSnapshot, lifecycle.publish(firstGeneration, firstSnapshot))

        lifecycle.stop()
        val secondGeneration = lifecycle.start()
        assertFalse(lifecycle.accepts(firstGeneration))
        assertTrue(lifecycle.accepts(secondGeneration))
        val staleSnapshot = firstSnapshot.copy(batteryPercent = 79)
        assertNull(lifecycle.publish(firstGeneration, staleSnapshot))
        assertEquals(firstSnapshot, lifecycle.snapshot())

        val currentSnapshot = firstSnapshot.copy(batteryPercent = 78)
        assertEquals(currentSnapshot, lifecycle.publish(secondGeneration, currentSnapshot))
        assertEquals(currentSnapshot, lifecycle.snapshot())
    }
}
