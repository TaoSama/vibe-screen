package dev.telemachus.display

import android.os.BatteryManager
import android.os.PowerManager
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class DeviceHealthMonitorTest {
    @Test
    fun `battery values are bounded and unknown inputs stay unknown`() {
        assertEquals(50, DeviceHealthPolicy.batteryPercent(1, 2))
        assertEquals(100, DeviceHealthPolicy.batteryPercent(12, 10))
        assertNull(DeviceHealthPolicy.batteryPercent(-1, 100))
        assertNull(DeviceHealthPolicy.batteryPercent(40, 0))
        assertEquals(true, DeviceHealthPolicy.isCharging(BatteryManager.BATTERY_STATUS_FULL))
        assertEquals(false, DeviceHealthPolicy.isCharging(BatteryManager.BATTERY_STATUS_DISCHARGING))
        assertNull(DeviceHealthPolicy.isCharging(BatteryManager.BATTERY_STATUS_UNKNOWN))
    }

    @Test
    fun `thermal severity takes priority over low battery guidance`() {
        assertEquals(DeviceHealthAttention.UNKNOWN, DeviceHealthPolicy.attention(DeviceHealthSnapshot()))
        assertEquals(
            DeviceHealthAttention.POWER_RECOMMENDED,
            DeviceHealthPolicy.attention(DeviceHealthSnapshot(20, charging = false)),
        )
        assertEquals(
            DeviceHealthAttention.THERMAL_ELEVATED,
            DeviceHealthPolicy.attention(
                DeviceHealthSnapshot(10, charging = false, thermalState = DeviceThermalState.ELEVATED),
            ),
        )
        assertEquals(
            DeviceHealthAttention.THERMAL_HIGH,
            DeviceHealthPolicy.attention(DeviceHealthSnapshot(90, charging = true, thermalState = DeviceThermalState.SEVERE)),
        )
        assertEquals(DeviceThermalState.CRITICAL, DeviceHealthPolicy.thermalState(PowerManager.THERMAL_STATUS_SHUTDOWN))
    }

    @Test
    fun `lifecycle emits changes once and rejects callbacks after stop`() {
        val lifecycle = DeviceHealthLifecycle()
        val changed = DeviceHealthSnapshot(72, charging = true, thermalState = DeviceThermalState.NOMINAL)

        assertNull(lifecycle.publish(changed))
        lifecycle.start()
        assertEquals(changed, lifecycle.publish(changed))
        assertNull(lifecycle.publish(changed))
        lifecycle.stop()
        assertNull(lifecycle.publish(changed.copy(batteryPercent = 71)))
        assertEquals(changed, lifecycle.snapshot())
    }
}
