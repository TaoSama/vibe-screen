@file:Suppress("UNUSED_PARAMETER")

package dev.telemachus.display

/** Release source-set no-op implementation of the Internet audio readiness test hook. */
internal object MainActivityInternetAudioReadinessTestHooks {
    data class Override(
        val active: Boolean,
        val snapshot: AudioReadinessSnapshot?,
    )

    fun setOverride(value: Override?) = Unit

    fun currentOverride(): Override? = null
}
