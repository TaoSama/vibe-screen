package dev.telemachus.display

/** Debug-only state injection for focused Internet audio readiness UI tests. */
internal object MainActivityInternetAudioReadinessTestHooks {
    data class Override(
        val active: Boolean,
        val snapshot: AudioReadinessSnapshot?,
    )

    @Volatile private var override: Override? = null

    fun setOverride(value: Override?) {
        override = value
    }

    fun currentOverride(): Override? = override
}
