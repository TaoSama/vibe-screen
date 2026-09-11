package dev.telemachus.display

import android.app.Activity
import androidx.test.core.app.ActivityScenario
import org.junit.Assert.assertEquals
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
                activity.setPrivateField("pendingResultRaw", VALID_PAIRING_QR)
                activity.setPrivateField("alreadyDelivered", true)
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

    private fun Any.setPrivateField(
        name: String,
        value: Any?,
    ) {
        privateField(name).set(this, value)
    }

    private fun Any.getPrivateField(name: String): Any? = privateField(name).get(this)

    private fun Any.privateField(name: String) =
        QRScannerActivity::class.java.getDeclaredField(name).apply { isAccessible = true }

    private companion object {
        private const val VALID_PAIRING_QR = "vibescreen://pair?v=1&o=test"
    }
}
