package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Test

class UsbConnectActionPolicyTest {
    @Test
    fun `fresh connection offers connect`() {
        assertEquals(
            UsbConnectActionPolicy.Action.CONNECT,
            UsbConnectActionPolicy.resolve(
                connectionAttemptInProgress = false,
                hasAttemptedConnection = false,
            ),
        )
    }

    @Test
    fun `active attempt reports connecting even after a prior failure`() {
        assertEquals(
            UsbConnectActionPolicy.Action.CONNECTING,
            UsbConnectActionPolicy.resolve(
                connectionAttemptInProgress = true,
                hasAttemptedConnection = true,
            ),
        )
    }

    @Test
    fun `completed failed attempt offers try again`() {
        assertEquals(
            UsbConnectActionPolicy.Action.TRY_AGAIN,
            UsbConnectActionPolicy.resolve(
                connectionAttemptInProgress = false,
                hasAttemptedConnection = true,
            ),
        )
    }
}
