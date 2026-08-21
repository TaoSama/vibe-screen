package dev.telemachus.display

import android.view.WindowManager

internal data class StreamingWindowFlagUpdate(
    val addFlags: Int,
    val clearFlags: Int,
)

internal object StreamingWindowStatePolicy {
    fun update(
        connected: Boolean,
        foreground: Boolean,
        secureFlag: Int,
    ): StreamingWindowFlagUpdate {
        val protectedFlags =
            WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON or
                WindowManager.LayoutParams.FLAG_SECURE
        if (!connected) {
            return StreamingWindowFlagUpdate(addFlags = 0, clearFlags = protectedFlags)
        }

        return if (foreground) {
            StreamingWindowFlagUpdate(
                addFlags = WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON or secureFlag,
                clearFlags = if (secureFlag == 0) WindowManager.LayoutParams.FLAG_SECURE else 0,
            )
        } else {
            StreamingWindowFlagUpdate(
                addFlags = WindowManager.LayoutParams.FLAG_SECURE,
                clearFlags = WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON,
            )
        }
    }
}
