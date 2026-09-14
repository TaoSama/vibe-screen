package dev.telemachus.display

internal class FileTransferDialogDecision {
    private var decided = false

    val isPending: Boolean
        get() = !decided

    fun tryFinish(admit: () -> Boolean = { true }): Boolean {
        if (decided || !admit()) return false
        decided = true
        return true
    }
}
