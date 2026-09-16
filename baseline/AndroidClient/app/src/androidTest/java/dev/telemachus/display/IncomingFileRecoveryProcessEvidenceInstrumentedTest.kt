package dev.telemachus.display

import android.content.Intent
import android.os.SystemClock
import android.widget.TextView
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.google.protobuf.ByteString
import dev.telemachus.display.protocol.CompletedIncomingFile
import dev.telemachus.display.protocol.sha256
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

@RunWith(AndroidJUnit4::class)
class IncomingFileRecoveryProcessEvidenceInstrumentedTest {
    @Test
    fun runRequestedPhase() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val store = IncomingFileRecoveryStore(context)
        val phase = InstrumentationRegistry.getArguments().getString(PHASE_ARGUMENT)
        assumeTrue("Run only through the external force-stop evidence flow", phase == PHASE_SEED || phase == PHASE_VERIFY)
        when (phase) {
            PHASE_SEED -> seedRecovery(context.cacheDir, store)
            PHASE_VERIFY -> verifyAndClearRecovery(store)
        }
    }

    private fun seedRecovery(
        cacheDirectory: File,
        store: IncomingFileRecoveryStore,
    ) {
        clearRecovery(store)
        val payload = ("force-stop-recovery" + "abcdef0123456789".repeat(128)).toByteArray()
        val staging = File(cacheDirectory, ".$DISPLAY_NAME.partial").apply { writeBytes(payload) }
        try {
            store.adopt(
                CompletedIncomingFile(
                    transferId = ByteString.copyFromUtf8("force-stop-recovery"),
                    fileName = DISPLAY_NAME,
                    mimeType = TEST_MIME_TYPE,
                    stagingFile = staging,
                    sha256 = sha256(payload),
                ),
                DISPLAY_NAME,
            )
            assertNotNull(store.load())
        } finally {
            staging.delete()
        }
    }

    private fun verifyAndClearRecovery(store: IncomingFileRecoveryStore) {
        try {
            assertNotNull("Recovery must survive the external process stop", store.load())
            val context = InstrumentationRegistry.getInstrumentation().targetContext
            ActivityScenario.launch<MainActivity>(
                Intent(context, MainActivity::class.java).putExtra("auto_connect", false),
            ).use { scenario ->
                val deadline = SystemClock.elapsedRealtime() + 10_000L
                while (SystemClock.elapsedRealtime() < deadline) {
                    var visible = false
                    scenario.onActivity { activity ->
                        visible =
                            activity.findViewById<TextView>(R.id.incomingFileStatusTitle).text.toString() ==
                                activity.getString(R.string.file_transfer_incoming_save_failed_title)
                    }
                    if (visible) return@use
                    SystemClock.sleep(50L)
                }
                assertTrue("Timed out waiting for recovered incoming file UI", false)
            }
        } finally {
            clearRecovery(store)
        }
    }

    private fun clearRecovery(store: IncomingFileRecoveryStore) {
        store.load()?.let(store::discard)
    }

    private companion object {
        const val PHASE_ARGUMENT = "incomingRecoveryExternalPhase"
        const val PHASE_SEED = "seed"
        const val PHASE_VERIFY = "verify"
        const val DISPLAY_NAME = "vibescreen-force-stop-recovery.bin"
        const val TEST_MIME_TYPE = "application/octet-stream"
    }
}
