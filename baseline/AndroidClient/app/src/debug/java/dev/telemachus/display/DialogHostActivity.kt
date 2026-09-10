package dev.telemachus.display

import android.app.Activity
import android.content.Context
import android.content.res.Configuration

internal class DialogHostActivity : Activity() {
    override fun attachBaseContext(newBase: Context) {
        val override = configurationOverride
        if (override == null) {
            super.attachBaseContext(newBase)
            return
        }
        val configuration =
            Configuration(newBase.resources.configuration).apply {
                screenWidthDp = override.widthDp
                screenHeightDp = override.heightDp
                smallestScreenWidthDp = minOf(override.widthDp, override.heightDp)
                fontScale = override.fontScale
                orientation =
                    if (override.widthDp > override.heightDp) {
                        Configuration.ORIENTATION_LANDSCAPE
                    } else {
                        Configuration.ORIENTATION_PORTRAIT
                    }
            }
        super.attachBaseContext(newBase.createConfigurationContext(configuration))
    }

    internal data class ConfigurationOverride(
        val widthDp: Int,
        val heightDp: Int,
        val fontScale: Float,
    )

    internal companion object {
        @Volatile
        var configurationOverride: ConfigurationOverride? = null
    }
}
