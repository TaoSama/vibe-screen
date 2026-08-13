package dev.telemachus.display

internal class ConnectionStatusAnnouncementCoordinator {
    private var lastAnnouncement: String? = null

    fun announceIfChanged(
        text: CharSequence,
        announce: (CharSequence) -> Unit,
    ): Boolean {
        val snapshot = text.toString()
        if (lastAnnouncement == snapshot) return false
        lastAnnouncement = snapshot
        announce(snapshot)
        return true
    }

    fun reset() {
        lastAnnouncement = null
    }
}
