package dev.telemachus.display

import android.text.TextUtils
import android.view.View
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

    fun show(
        label: TextView,
        text: CharSequence,
    ): Boolean {
        label.visibility = View.VISIBLE
        return apply(label, text)
    }

    fun hide(label: TextView): Boolean {
        label.visibility = View.GONE
        return apply(label, "")
    }
}
