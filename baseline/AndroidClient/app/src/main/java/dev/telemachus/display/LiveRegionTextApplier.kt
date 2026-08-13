package dev.telemachus.display

import android.text.TextUtils
import android.widget.TextView

internal object LiveRegionTextApplier {
    fun apply(
        label: TextView,
        text: CharSequence,
    ): Boolean {
        if (TextUtils.equals(label.text, text)) return false
        label.text = text
        return true
    }
}
