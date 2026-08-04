package dev.telemachus.display.internet

import java.util.concurrent.atomic.AtomicReference

/** Separates ownership of installation from successful completion. */
internal class DecoderConfigurationCommitGate {
    private val state = AtomicReference(State.PENDING)

    fun startInstallation(): Boolean = state.compareAndSet(State.PENDING, State.INSTALLING)

    fun cancelPending(): Boolean = state.compareAndSet(State.PENDING, State.CANCELLED)

    fun markDone(): Boolean = state.compareAndSet(State.INSTALLING, State.DONE)

    fun markFailed(): Boolean = state.compareAndSet(State.INSTALLING, State.FAILED)

    val done: Boolean
        get() = state.get() == State.DONE

    val installationOwned: Boolean
        get() = state.get() == State.INSTALLING

    private enum class State { PENDING, INSTALLING, DONE, FAILED, CANCELLED }
}
