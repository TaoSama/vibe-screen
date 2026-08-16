package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Test

class UsbTransportDisplayPolicyTest {
    @Test
    fun subtitleRefreshOwnershipRemainsUsbOnly() {
        assertEquals(true, UsbTransportDisplayPolicy.shouldRefreshSubtitle(ConnectionMode.USB))
        assertEquals(false, UsbTransportDisplayPolicy.shouldRefreshSubtitle(ConnectionMode.WIRELESS))
        assertEquals(false, UsbTransportDisplayPolicy.shouldRefreshSubtitle(ConnectionMode.INTERNET))
    }

    @Test
    fun adbStateMatrixProjectsHonestLabelsAndReadiness() {
        val cases =
            listOf(
                Case(
                    name = "USB only",
                    snapshot = snapshot(usbDebug = true, usbData = true, usbAdbFunction = true, server = true),
                    transport = AdbTransportKind.USB,
                    subtitle = R.string.usb_waiting_description,
                    debuggingLabel = R.string.usb_debugging,
                    transportLabel = R.string.usb_data_link,
                    ready = true,
                ),
                Case(
                    name = "wireless only with ADB_ENABLED zero",
                    snapshot = snapshot(wireless = true, server = true),
                    transport = AdbTransportKind.WIRELESS,
                    subtitle = R.string.wireless_adb_waiting_description,
                    debuggingLabel = R.string.wireless_debugging,
                    transportLabel = R.string.wireless_debugging_connection,
                    ready = true,
                ),
                Case(
                    name = "USB and wireless prefers active USB debugging",
                    snapshot =
                        snapshot(
                            usbDebug = true,
                            wireless = true,
                            usbData = true,
                            usbAdbFunction = true,
                            server = true,
                        ),
                    transport = AdbTransportKind.USB,
                    subtitle = R.string.usb_waiting_description,
                    debuggingLabel = R.string.usb_debugging,
                    transportLabel = R.string.usb_data_link,
                    ready = true,
                ),
                Case(
                    name = "USB data with only wireless debugging uses wireless ADB",
                    snapshot = snapshot(wireless = true, usbData = true, server = true),
                    transport = AdbTransportKind.WIRELESS,
                    subtitle = R.string.wireless_adb_waiting_description,
                    debuggingLabel = R.string.wireless_debugging,
                    transportLabel = R.string.wireless_debugging_connection,
                    ready = true,
                ),
                Case(
                    name = "debugging enabled without a data route",
                    snapshot = snapshot(usbDebug = true, server = true),
                    transport = AdbTransportKind.UNAVAILABLE,
                    subtitle = R.string.adb_transport_waiting_description,
                    debuggingLabel = R.string.usb_debugging,
                    transportLabel = R.string.usb_data_link_or_wireless_debugging,
                    ready = false,
                ),
                Case(
                    name = "USB setting and data without an active ADB function",
                    snapshot = snapshot(usbDebug = true, usbData = true, server = true),
                    transport = AdbTransportKind.UNAVAILABLE,
                    subtitle = R.string.adb_transport_waiting_description,
                    debuggingLabel = R.string.usb_debugging,
                    transportLabel = R.string.usb_data_link,
                    ready = false,
                    debuggingStatus = ChecklistStatus.NOT_READY,
                ),
                Case(
                    name = "USB data without any debugging channel",
                    snapshot = snapshot(usbData = true, server = true),
                    transport = AdbTransportKind.UNAVAILABLE,
                    subtitle = R.string.adb_transport_waiting_description,
                    debuggingLabel = R.string.usb_or_wireless_debugging,
                    transportLabel = R.string.usb_data_link,
                    ready = false,
                ),
                Case(
                    name = "server missing",
                    snapshot = snapshot(usbDebug = true, usbData = true, usbAdbFunction = true),
                    transport = AdbTransportKind.USB,
                    subtitle = R.string.usb_waiting_description,
                    debuggingLabel = R.string.usb_debugging,
                    transportLabel = R.string.usb_data_link,
                    ready = false,
                ),
                Case(
                    name = "developer mode off",
                    snapshot = snapshot(developer = false, wireless = true, server = true),
                    transport = AdbTransportKind.WIRELESS,
                    subtitle = R.string.wireless_adb_waiting_description,
                    debuggingLabel = R.string.wireless_debugging,
                    transportLabel = R.string.wireless_debugging_connection,
                    ready = false,
                ),
                Case(
                    name = "USB setting without a cable falls back to wireless",
                    snapshot = snapshot(usbDebug = true, wireless = true, server = true),
                    transport = AdbTransportKind.WIRELESS,
                    subtitle = R.string.wireless_adb_waiting_description,
                    debuggingLabel = R.string.wireless_debugging,
                    transportLabel = R.string.wireless_debugging_connection,
                    ready = true,
                ),
                Case(
                    name = "no transport signals",
                    snapshot = snapshot(server = true),
                    transport = AdbTransportKind.UNAVAILABLE,
                    subtitle = R.string.adb_transport_waiting_description,
                    debuggingLabel = R.string.usb_or_wireless_debugging,
                    transportLabel = R.string.usb_data_link_or_wireless_debugging,
                    ready = false,
                ),
            )

        cases.forEach { case ->
            val projection = UsbTransportDisplayPolicy.project(case.snapshot)
            assertEquals(case.name, case.transport, case.snapshot.adbTransport)
            assertEquals(case.name, case.subtitle, projection.subtitleResource)
            assertEquals(case.name, case.debuggingLabel, projection.debuggingLabelResource)
            assertEquals(case.name, case.transportLabel, projection.transportLabelResource)
            assertEquals(case.name, case.ready, projection.allReady)
            assertEquals(
                case.name,
                case.debuggingStatus
                    ?: if (
                        case.snapshot.adbTransport != AdbTransportKind.UNAVAILABLE ||
                        (case.snapshot.usbDebuggingSettingEnabled && !case.snapshot.usbDataConnected)
                    ) ChecklistStatus.READY else ChecklistStatus.NOT_READY,
                projection.debuggingStatus,
            )
            assertEquals(
                case.name,
                if (case.snapshot.usbDataConnected || case.snapshot.wirelessDebuggingEnabled) {
                    ChecklistStatus.READY
                } else {
                    ChecklistStatus.NOT_READY
                },
                projection.transportStatus,
            )
        }
    }

    @Test
    fun wirelessConnectionStillRequiresServerProbe() {
        val withoutServer = UsbTransportDisplayPolicy.project(snapshot(wireless = true))
        val withServer = UsbTransportDisplayPolicy.project(snapshot(wireless = true, server = true))

        assertEquals(R.string.wireless_debugging_connection, withoutServer.transportLabelResource)
        assertEquals(false, withoutServer.allReady)
        assertEquals(true, withServer.allReady)
    }

    private fun snapshot(
        developer: Boolean = true,
        usbDebug: Boolean = false,
        wireless: Boolean = false,
        usbData: Boolean = false,
        usbAdbFunction: Boolean = false,
        server: Boolean = false,
    ) = UsbTransportDisplayPolicy.Snapshot(
        developerModeEnabled = developer,
        usbDebuggingSettingEnabled = usbDebug,
        wirelessDebuggingEnabled = wireless,
        usbDataConnected = usbData,
        usbAdbFunctionEnabled = usbAdbFunction,
        serverRunning = server,
    )

    private data class Case(
        val name: String,
        val snapshot: UsbTransportDisplayPolicy.Snapshot,
        val transport: AdbTransportKind,
        val subtitle: Int,
        val debuggingLabel: Int,
        val transportLabel: Int,
        val ready: Boolean,
        val debuggingStatus: ChecklistStatus? = null,
    )
}
