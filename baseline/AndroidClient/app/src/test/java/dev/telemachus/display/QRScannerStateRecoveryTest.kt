package dev.telemachus.display

import android.app.Activity
import android.os.Bundle
import androidx.lifecycle.Lifecycle
import androidx.test.core.app.ActivityScenario
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class QRScannerStateRecoveryTest {
    @Test
    fun recreateRestoresPendingResultAndFinishesWithOk() {
        ActivityScenario.launchActivityForResult(QRScannerActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                activity.deliveryGate().restorePending(VALID_PAIRING_QR)
            }

            scenario.recreate()

            assertEquals(Activity.RESULT_OK, scenario.result.resultCode)
            assertEquals(VALID_PAIRING_QR, scenario.result.resultData?.getStringExtra(QRScannerActivity.EXTRA_URL))
        }
    }

    @Test
    fun recreateRestoresWaitingForSettingsGrantWithoutCameraHardware() {
        ActivityScenario.launch(QRScannerActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                activity.setPrivateField("waitingForSettingsGrant", true)
            }

            scenario.recreate()

            scenario.onActivity { activity ->
                assertTrue(activity.getPrivateField("waitingForSettingsGrant") as Boolean)
            }
        }
    }

    @Test
    fun stateSavedThenLateAcceptedScanIsRejectedByOldInstance() {
        ActivityScenario.launch(QRScannerActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                val gate = activity.deliveryGate()
                val outState = Bundle()

                activity.callOnSaveInstanceState(outState)

                assertFalse(outState.containsKey(KEY_PENDING_RESULT_RAW))
                assertFalse(gate.tryClaimAccepted(VALID_PAIRING_QR))
                val snapshot = gate.snapshotForSave()
                assertEquals(QRScannerDeliveryClaimState.UNCLAIMED, snapshot.claimState)
            }
        }
    }

    @Test
    fun sameInstanceReopensGateAfterStateSaveWhenStartedAgain() {
        ActivityScenario.launch(QRScannerActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                val gate = activity.deliveryGate()

                activity.callOnSaveInstanceState(Bundle())
                assertFalse(gate.tryClaimAccepted(VALID_PAIRING_QR))
            }

            scenario.moveToState(Lifecycle.State.CREATED)
            scenario.moveToState(Lifecycle.State.RESUMED)

            scenario.onActivity { activity ->
                val gate = activity.deliveryGate()
                assertTrue(gate.tryClaimAccepted(VALID_PAIRING_QR))
            }
        }
    }

    private fun Any.setPrivateField(
        name: String,
        value: Any?,
    ) {
        privateField(name).set(this, value)
    }

    private fun Any.getPrivateField(name: String): Any? = privateField(name).get(this)

    private fun Any.deliveryGate(): QRScannerDeliveryGate =
        getPrivateField("resultDeliveryGate") as QRScannerDeliveryGate

    private fun QRScannerActivity.callOnSaveInstanceState(outState: Bundle) {
        QRScannerActivity::class.java
            .getDeclaredMethod("onSaveInstanceState", Bundle::class.java)
            .apply { isAccessible = true }
            .invoke(this, outState)
    }

    private fun Any.privateField(name: String) =
        QRScannerActivity::class.java.getDeclaredField(name).apply { isAccessible = true }

    private companion object {
        private const val KEY_PENDING_RESULT_RAW = "qr_scanner_pending_result_raw"
        private const val VALID_PAIRING_QR = "vibescreen://pair?v=1&o=test"
    }
}
