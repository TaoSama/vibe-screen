package dev.telemachus.display

import android.view.WindowManager
import org.junit.Assert.assertEquals
import org.junit.Test

class StreamingWindowStatePolicyTest {
    @Test
    fun `foreground connected stream keeps screen on and protects screenshots`() {
        val update =
            StreamingWindowStatePolicy.update(
                connected = true,
                foreground = true,
                secureFlag = WindowManager.LayoutParams.FLAG_SECURE,
            )

        assertEquals(
            WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON or WindowManager.LayoutParams.FLAG_SECURE,
            update.addFlags,
        )
        assertEquals(0, update.clearFlags)
    }

    @Test
    fun `background connected stream drops keep screen on but keeps screenshot protection`() {
        val update =
            StreamingWindowStatePolicy.update(
                connected = true,
                foreground = false,
                secureFlag = WindowManager.LayoutParams.FLAG_SECURE,
            )

        assertEquals(WindowManager.LayoutParams.FLAG_SECURE, update.addFlags)
        assertEquals(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON, update.clearFlags)
    }

    @Test
    fun `debug capture opt in clears secure flag only while foregrounded`() {
        val foreground =
            StreamingWindowStatePolicy.update(
                connected = true,
                foreground = true,
                secureFlag = 0,
            )
        val background =
            StreamingWindowStatePolicy.update(
                connected = true,
                foreground = false,
                secureFlag = 0,
            )

        assertEquals(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON, foreground.addFlags)
        assertEquals(WindowManager.LayoutParams.FLAG_SECURE, foreground.clearFlags)
        assertEquals(WindowManager.LayoutParams.FLAG_SECURE, background.addFlags)
        assertEquals(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON, background.clearFlags)
    }

    @Test
    fun `disconnected state clears both streaming window flags`() {
        val update =
            StreamingWindowStatePolicy.update(
                connected = false,
                foreground = true,
                secureFlag = WindowManager.LayoutParams.FLAG_SECURE,
            )

        assertEquals(0, update.addFlags)
        assertEquals(
            WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON or WindowManager.LayoutParams.FLAG_SECURE,
            update.clearFlags,
        )
    }
}
