package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Test

class UsbTransportDisplayPolicyTest {
    @Test
    fun `subtitle refresh is limited to USB mode`() {
        assertEquals(
            true,
            UsbTransportDisplayPolicy.shouldRefreshSubtitle(ConnectionMode.USB),
        )
        assertEquals(
            false,
            UsbTransportDisplayPolicy.shouldRefreshSubtitle(ConnectionMode.WIRELESS),
        )
        assertEquals(
            false,
            UsbTransportDisplayPolicy.shouldRefreshSubtitle(ConnectionMode.INTERNET),
        )
    }

    @Test
    fun `subtitle asks to keep the USB cable connected when the cable is present`() {
        assertEquals(
            R.string.usb_waiting_description,
            UsbTransportDisplayPolicy.subtitleResource(
                isUsbConnected = true,
                isWirelessAdbEnabled = false,
            ),
        )
    }

    @Test
    fun `subtitle prefers the USB cable when both transports are available`() {
        assertEquals(
            R.string.usb_waiting_description,
            UsbTransportDisplayPolicy.subtitleResource(
                isUsbConnected = true,
                isWirelessAdbEnabled = true,
            ),
        )
    }

    @Test
    fun `subtitle refers to wireless ADB when the USB cable is absent`() {
        assertEquals(
            R.string.wireless_adb_waiting_description,
            UsbTransportDisplayPolicy.subtitleResource(
                isUsbConnected = false,
                isWirelessAdbEnabled = true,
            ),
        )
    }

    @Test
    fun subtitleExplainsBothOptionsWhenNoAdbTransportIsReady() {
        assertEquals(
            R.string.adb_transport_waiting_description,
            UsbTransportDisplayPolicy.subtitleResource(
                isUsbConnected = false,
                isWirelessAdbEnabled = false,
            ),
        )
    }

    @Test
    fun `cable row labels the USB data cable when the cable is connected`() {
        assertEquals(
            R.string.usb_data_cable,
            UsbTransportDisplayPolicy.cableLabelResource(
                isUsbConnected = true,
                isWirelessAdbEnabled = true,
            ),
        )
    }

    @Test
    fun `cable row labels USB when only the USB data link is available`() {
        assertEquals(
            R.string.usb_data_cable,
            UsbTransportDisplayPolicy.cableLabelResource(
                isUsbConnected = true,
                isWirelessAdbEnabled = false,
            ),
        )
    }

    @Test
    fun `cable row labels wireless ADB when the cable is absent but ADB is enabled`() {
        assertEquals(
            R.string.wireless_adb,
            UsbTransportDisplayPolicy.cableLabelResource(
                isUsbConnected = false,
                isWirelessAdbEnabled = true,
            ),
        )
    }

    @Test
    fun `cable row keeps the USB data cable label when neither transport is available`() {
        assertEquals(
            R.string.usb_or_wireless_adb,
            UsbTransportDisplayPolicy.cableLabelResource(
                isUsbConnected = false,
                isWirelessAdbEnabled = false,
            ),
        )
    }

    @Test
    fun `cable row is ready when the USB cable is connected`() {
        assertEquals(
            ChecklistStatus.READY,
            UsbTransportDisplayPolicy.cableStatus(
                isUsbConnected = true,
                isWirelessAdbEnabled = false,
            ),
        )
    }

    @Test
    fun `cable row is ready when ADB is enabled over wireless`() {
        assertEquals(
            ChecklistStatus.READY,
            UsbTransportDisplayPolicy.cableStatus(
                isUsbConnected = false,
                isWirelessAdbEnabled = true,
            ),
        )
    }

    @Test
    fun `cable row is not ready when neither the cable nor ADB is available`() {
        assertEquals(
            ChecklistStatus.NOT_READY,
            UsbTransportDisplayPolicy.cableStatus(
                isUsbConnected = false,
                isWirelessAdbEnabled = false,
            ),
        )
    }

    @Test
    fun wirelessDebuggingIsReadyWithoutUsbDebugging() {
        assertEquals(
            R.string.wireless_debugging,
            UsbTransportDisplayPolicy.debuggingLabelResource(
                isUsbConnected = false,
                isUsbDebuggingEnabled = false,
                isWirelessAdbEnabled = true,
            ),
        )
        assertEquals(
            true,
            UsbTransportDisplayPolicy.allReady(
                isDeveloperModeEnabled = true,
                isUsbDebuggingEnabled = false,
                isWirelessAdbEnabled = true,
                isUsbConnected = false,
                isServerRunning = true,
            ),
        )
    }

    @Test
    fun usbDebuggingIsReadyWithAnActiveUsbDataLink() {
        assertEquals(
            true,
            UsbTransportDisplayPolicy.allReady(
                isDeveloperModeEnabled = true,
                isUsbDebuggingEnabled = true,
                isWirelessAdbEnabled = false,
                isUsbConnected = true,
                isServerRunning = true,
            ),
        )
    }

    @Test
    fun allReadyWhenUsbAndWirelessDebuggingAreBothAvailable() {
        assertEquals(
            true,
            UsbTransportDisplayPolicy.allReady(
                isDeveloperModeEnabled = true,
                isUsbDebuggingEnabled = true,
                isWirelessAdbEnabled = true,
                isUsbConnected = true,
                isServerRunning = true,
            ),
        )
    }

    @Test
    fun usbDebuggingAloneIsNotReadyWithoutADataLink() {
        assertEquals(
            false,
            UsbTransportDisplayPolicy.allReady(
                isDeveloperModeEnabled = true,
                isUsbDebuggingEnabled = true,
                isWirelessAdbEnabled = false,
                isUsbConnected = false,
                isServerRunning = true,
            ),
        )
    }

    @Test
    fun usbDataLinkIsNotReadyWithoutAnyDebuggingTransport() {
        assertEquals(
            false,
            UsbTransportDisplayPolicy.allReady(
                isDeveloperModeEnabled = true,
                isUsbDebuggingEnabled = false,
                isWirelessAdbEnabled = false,
                isUsbConnected = true,
                isServerRunning = true,
            ),
        )
    }

    @Test
    fun wirelessDebuggingLabelWinsWhenUsbDebuggingIsEnabledWithoutAUsbLink() {
        assertEquals(
            R.string.wireless_debugging,
            UsbTransportDisplayPolicy.debuggingLabelResource(
                isUsbConnected = false,
                isUsbDebuggingEnabled = true,
                isWirelessAdbEnabled = true,
            ),
        )
    }

    @Test
    fun usbDebuggingLabelWinsWhenTheUsbDataLinkIsActive() {
        assertEquals(
            R.string.usb_debugging,
            UsbTransportDisplayPolicy.debuggingLabelResource(
                isUsbConnected = true,
                isUsbDebuggingEnabled = true,
                isWirelessAdbEnabled = true,
            ),
        )
    }

    @Test
    fun wirelessDebuggingLabelShowsWhenUsbIsConnectedWithoutUsbDebugging() {
        assertEquals(
            R.string.wireless_debugging,
            UsbTransportDisplayPolicy.debuggingLabelResource(
                isUsbConnected = true,
                isUsbDebuggingEnabled = false,
                isWirelessAdbEnabled = true,
            ),
        )
    }

    @Test
    fun usbDebuggingLabelShowsWhenUsbDebuggingEnabledWithoutCableOrWireless() {
        assertEquals(
            R.string.usb_debugging,
            UsbTransportDisplayPolicy.debuggingLabelResource(
                isUsbConnected = false,
                isUsbDebuggingEnabled = true,
                isWirelessAdbEnabled = false,
            ),
        )
    }

    @Test
    fun noDebuggingLabelShowsWhenUsbIsConnectedWithoutAnyDebuggingTransport() {
        assertEquals(
            R.string.usb_or_wireless_debugging,
            UsbTransportDisplayPolicy.debuggingLabelResource(
                isUsbConnected = true,
                isUsbDebuggingEnabled = false,
                isWirelessAdbEnabled = false,
            ),
        )
    }

    @Test
    fun noDebuggingTransportIsNotReady() {
        assertEquals(
            R.string.usb_or_wireless_debugging,
            UsbTransportDisplayPolicy.debuggingLabelResource(
                isUsbConnected = false,
                isUsbDebuggingEnabled = false,
                isWirelessAdbEnabled = false,
            ),
        )
        assertEquals(
            false,
            UsbTransportDisplayPolicy.allReady(
                isDeveloperModeEnabled = true,
                isUsbDebuggingEnabled = false,
                isWirelessAdbEnabled = false,
                isUsbConnected = false,
                isServerRunning = true,
            ),
        )
    }

    @Test
    fun missingMacServerIsNotReady() {
        assertEquals(
            false,
            UsbTransportDisplayPolicy.allReady(
                isDeveloperModeEnabled = true,
                isUsbDebuggingEnabled = false,
                isWirelessAdbEnabled = true,
                isUsbConnected = false,
                isServerRunning = false,
            ),
        )
    }

    @Test
    fun disabledDeveloperModeIsNotReady() {
        assertEquals(
            false,
            UsbTransportDisplayPolicy.allReady(
                isDeveloperModeEnabled = false,
                isUsbDebuggingEnabled = false,
                isWirelessAdbEnabled = true,
                isUsbConnected = false,
                isServerRunning = true,
            ),
        )
    }
}
