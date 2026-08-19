package dev.telemachus.display

/**
 * Resolves the Internet security-description disclosure independently from the
 * connection panel geometry. Security guidance stays fully visible in every
 * mode; the surrounding scroll view owns any small-screen overflow.
 */
internal object ConnectionSubtitleDisclosurePolicy {
    const val MAX_LINES_UNLIMITED = Int.MAX_VALUE

    data class Presentation(
        val expandable: Boolean,
        val expanded: Boolean,
        val maxLines: Int,
        val ellipsizeEnd: Boolean,
    )

    @Suppress("UNUSED_PARAMETER")
    fun resolve(
        connectionMode: ConnectionMode,
        stackedPortrait: Boolean,
        requestedExpanded: Boolean,
    ): Presentation =
        Presentation(
            expandable = false,
            expanded = false,
            maxLines = MAX_LINES_UNLIMITED,
            ellipsizeEnd = false,
        )
}

internal class ConnectionSubtitleDisclosureState {
    var expanded: Boolean = false
        private set

    fun toggle() {
        expanded = !expanded
    }

    fun reset() {
        expanded = false
    }
}
