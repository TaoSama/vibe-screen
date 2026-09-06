package dev.telemachus.display

import android.view.InputDevice
import android.view.MotionEvent
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PeripheralInputDiagnosticsTest {
    @Test
    fun nativePointerUnsupportedDiagnosticNamesCapabilityAndExternalGateBoundary() {
        val diagnostic =
            PeripheralInputDiagnostics.nativePointerUnsupported(
                input = ClientPointerInput(
                    action = ClientPointerAction.BUTTON_PRESS,
                    x = 12.5f,
                    y = 7f,
                    buttonState = MotionEvent.BUTTON_PRIMARY,
                    actionButton = MotionEvent.BUTTON_PRIMARY,
                ),
                capabilities = ClientSessionCapabilities.LEGACY_TOUCH_ONLY,
            )

        assertEquals(PeripheralInputDiagnosticKind.NATIVE_POINTER_UNNEGOTIATED, diagnostic.kind)
        assertEquals("usb_lan", diagnostic.fields["transport"])
        assertEquals("native_pointer", diagnostic.fields["capability"])
        assertEquals("false", diagnostic.fields["negotiated"])
        assertEquals("true", diagnostic.fields["touch_only"])
        assertEquals("button_press", diagnostic.fields["action"])
        assertMessageCarriesExternalGateBoundary(diagnostic)
    }

    @Test
    fun nativePointerForwardedDiagnosticUsesDeviceSourcesAndWireButtons() {
        val diagnostic =
            PeripheralInputDiagnostics.nativePointerForwarded(
                eventDeviceId = 9,
                eventSource = InputDevice.SOURCE_MOUSE,
                inputDeviceSources = InputDevice.SOURCE_MOUSE or InputDevice.SOURCE_TOUCHPAD,
                eventButtonState = MotionEvent.BUTTON_PRIMARY or MotionEvent.BUTTON_TERTIARY,
                eventActionButton = MotionEvent.BUTTON_PRIMARY,
                input = ClientPointerInput(
                    action = ClientPointerAction.MOVE,
                    x = 10.25f,
                    y = 20.5f,
                ),
            )

        assertEquals("native_pointer_forwarded", diagnostic.kind.wireName)
        assertEquals("9", diagnostic.fields["device_id"])
        assertEquals("MOUSE+TOUCHPAD", diagnostic.fields["sources"])
        assertEquals(NativeInputWire.BUTTON_PRIMARY.toString(), diagnostic.fields["wire_buttons"])
        assertEquals("10.25", diagnostic.fields["x"])
        assertEquals("20.5", diagnostic.fields["y"])
        assertMessageCarriesExternalGateBoundary(diagnostic)
    }

    @Test
    fun controllerDiagnosticsNormalizeSourcesAndHostRejectionReasons() {
        val unsupported =
            PeripheralInputDiagnostics.controllerCapabilityUnsupported(
                PeripheralInputDiagnosticTransport.USB_LAN,
                source = "controller hotplug foreground",
            )
        val sinkRejected =
            PeripheralInputDiagnostics.controllerSinkRejected(
                PeripheralInputDiagnosticTransport.INTERNET,
                source = "internet controller release",
            )
        val hostRejected =
            PeripheralInputDiagnostics.controllerHostRejected(
                transport = PeripheralInputDiagnosticTransport.INTERNET,
                controllerId = "pad 1",
                controllerEpoch = 3,
                rejectionReason = "  ",
                inputId = 42,
            )

        assertEquals("controller_hotplug_foreground", unsupported.fields["source"])
        assertEquals("internet", sinkRejected.fields["transport"])
        assertEquals("internet_controller_release", sinkRejected.fields["source"])
        assertEquals("42", hostRejected.fields["input_id"])
        assertEquals("pad_1", hostRejected.fields["controller_id"])
        assertEquals("unspecified", hostRejected.fields["rejection_reason"])
        assertMessageCarriesExternalGateBoundary(hostRejected)
    }

    @Test
    fun controllerHotplugDiagnosticsReportLimitReasonWithoutClosingRuntimeGate() {
        val synchronized =
            PeripheralInputDiagnostics.controllerHotplugSynchronized(
                reason = "device changed 7",
                availableDeviceCount = 5,
                result = ControllerHotplugSyncResult(
                    connected = 1,
                    disconnected = 0,
                    resynchronized = true,
                    limitReached = 1,
                ),
            )
        val limit =
            PeripheralInputDiagnostics.controllerLimitReached(
                reason = "device changed 7",
                availableDeviceCount = 5,
                limitReached = 1,
            )

        assertEquals("5", synchronized.fields["available_devices"])
        assertEquals("true", synchronized.fields["resynchronized"])
        assertEquals(MAXIMUM_ACTIVE_CONTROLLERS.toString(), limit.fields["active_limit"])
        assertEquals(MAXIMUM_ACTIVE_CONTROLLERS_REJECTION_REASON, limit.fields["rejection_reason"])
        assertMessageCarriesExternalGateBoundary(limit)
    }

    @Test
    fun unsupportedPeripheralDiagnosticKeepsExactRejectionReason() {
        val diagnostic = PeripheralInputDiagnostics.unsupportedPeripheralKind("vendor-device")

        assertEquals(PeripheralInputDiagnosticKind.UNSUPPORTED_PERIPHERAL_KIND, diagnostic.kind)
        assertEquals("peripheral_input_framework", diagnostic.fields["capability"])
        assertEquals("vendor-device", diagnostic.fields["peripheral_kind"])
        assertEquals(UNSUPPORTED_PERIPHERAL_KIND_REJECTION_REASON, diagnostic.fields["rejection_reason"])
        assertMessageCarriesExternalGateBoundary(diagnostic)
    }

    private fun assertMessageCarriesExternalGateBoundary(diagnostic: PeripheralInputDiagnostic) {
        val message = diagnostic.message()
        assertTrue(message.startsWith("peripheral_input kind=" + diagnostic.kind.wireName))
        assertTrue(message.contains(" acceptance_evidence=external_gate_required"))
        assertFalse(message.contains("gate_closed=true"))
        assertFalse(message.contains(' ' + "rejection_reason= ", ignoreCase = false))
    }
}
