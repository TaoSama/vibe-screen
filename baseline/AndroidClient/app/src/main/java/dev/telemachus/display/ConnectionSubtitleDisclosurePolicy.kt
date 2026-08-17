package dev.telemachus.display

/**
 * Resolves the Internet security-description disclosure independently from the
 * connection panel geometry. USB/LAN guidance and every landscape layout keep
 * their full text; only the stacked portrait Internet preview starts compact.
 */
internal object ConnectionSubtitleDisclosurePolicy {
    const val COLLAPSED_MAX_LINES = 3
    const val MAX_LINES_UNLIMITED = Int.MAX_VALUE

    data class Presentation(
        val expandable: Boolean,
        val expanded: Boolean,
        val maxLines: Int,
        val ellipsizeEnd: Boolean,
    )

    fun resolve(
        connectionMode: ConnectionMode,
        stackedPortrait: Boolean,
        requestedExpanded: Boolean,
    ): Presentation {
        val expandable = connectionMode == ConnectionMode.INTERNET && stackedPortrait
        val expanded = expandable && requestedExpanded
        return Presentation(
            expandable = expandable,
            expanded = expanded,
            maxLines =
                if (expandable && !expanded) {
                    COLLAPSED_MAX_LINES
                } else {
                    MAX_LINES_UNLIMITED
                },
            ellipsizeEnd = expandable && !expanded,
        )
    }
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
