package dev.telemachus.display

internal sealed interface DecoderStartupCommitResult {
    data object Committed : DecoderStartupCommitResult

    data object NotCommitted : DecoderStartupCommitResult

    data class Failed(
        val failure: DecoderFailure,
    ) : DecoderStartupCommitResult {
        val reason: String
            get() = failure.reason
    }
}

enum class DecoderFailureKind {
    STRUCTURAL_TARGET_UNSUPPORTED,
    SESSION_RUNTIME_FAILURE,
}

internal const val STRUCTURAL_HEVC_TARGET_UNSUPPORTED_REASON = "hevc_target_unsupported"

data class DecoderFailure(
    val kind: DecoderFailureKind,
    val reason: String,
)

internal class DecoderInitializationException(
    val failure: DecoderFailure,
) : UnsupportedOperationException(failure.reason)

internal class DecoderStartupGate(
    private val onKeyframeRequired: (force: Boolean, reason: String) -> Unit,
    private val onCodecFailure: (failure: DecoderFailure) -> Unit,
) {
    private val lock = Any()
    private var state = State.STARTING
    private var fatalFailure: DecoderFailure? = null
    private val pendingEvents = ArrayDeque<Event>()

    fun start(startCodec: () -> Unit) {
        startCodec()
    }

    fun requestKeyframe(
        force: Boolean,
        reason: String,
    ) {
        dispatchOrQueue(Event.Keyframe(force, reason))
    }

    fun reportFatal(
        failure: DecoderFailure,
        keyframeReason: String,
    ) {
        val events = listOf(Event.Keyframe(force = true, reason = keyframeReason), Event.Failure(failure))
        val dispatchNow =
            synchronized(lock) {
                if (state == State.DISCARDED || fatalFailure != null) {
                    false
                } else {
                    fatalFailure = failure
                    if (state == State.STARTING) pendingEvents.addAll(events)
                    state != State.STARTING
                }
            }
        if (dispatchNow) events.forEach(::dispatch)
    }

    fun commit(publish: () -> Boolean): DecoderStartupCommitResult {
        val resolution =
            synchronized(lock) {
                check(state == State.STARTING) { "Decoder startup already resolved" }
                val failure = fatalFailure
                when {
                    failure != null -> {
                        state = State.FAILED
                        val events = pendingEvents.toList()
                        pendingEvents.clear()
                        DecoderStartupCommitResult.Failed(failure) to events
                    }
                    !publish() -> {
                        state = State.DISCARDED
                        pendingEvents.clear()
                        DecoderStartupCommitResult.NotCommitted to emptyList()
                    }
                    else -> {
                        state = State.COMMITTED
                        val events = pendingEvents.toList()
                        pendingEvents.clear()
                        DecoderStartupCommitResult.Committed to events
                    }
                }
            }
        resolution.second.forEach(::dispatch)
        return resolution.first
    }

    fun discard() {
        synchronized(lock) {
            state = State.DISCARDED
            pendingEvents.clear()
        }
    }

    private fun dispatchOrQueue(event: Event) {
        val dispatchNow =
            synchronized(lock) {
                when (state) {
                    State.STARTING -> {
                        pendingEvents.addLast(event)
                        false
                    }
                    State.COMMITTED, State.FAILED -> true
                    State.DISCARDED -> false
                }
            }
        if (dispatchNow) dispatch(event)
    }

    private fun dispatch(event: Event) {
        when (event) {
            is Event.Keyframe -> onKeyframeRequired(event.force, event.reason)
            is Event.Failure -> onCodecFailure(event.failure)
        }
    }

    private enum class State {
        STARTING,
        COMMITTED,
        FAILED,
        DISCARDED,
    }

    private sealed interface Event {
        data class Keyframe(
            val force: Boolean,
            val reason: String,
        ) : Event

        data class Failure(
            val failure: DecoderFailure,
        ) : Event
    }
}
