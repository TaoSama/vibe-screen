package dev.telemachus.display

import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class DecoderStartupGateTest {
    @Test
    fun synchronousStartErrorDeliversRecoveryAndRejectsAccept() {
        val events = mutableListOf<String>()
        val accepted = AtomicBoolean()
        val gate = gate(events)
        val codec = FakeCodec { gate.reportFatal(FATAL_REASON, KEYFRAME_REASON) }

        gate.start(codec::start)
        val result = gate.commit {
            accepted.set(true)
            true
        }

        assertEquals(DecoderStartupCommitResult.Failed(FATAL_REASON), result)
        assertFalse(accepted.get())
        assertEquals(listOf("keyframe:true:$KEYFRAME_REASON", "fallback:$FATAL_REASON"), events)
    }

    @Test
    fun asynchronousStartErrorBeforeCommitCannotProduceAccept() {
        val events = mutableListOf<String>()
        val accepted = AtomicBoolean()
        val errorDelivered = CountDownLatch(1)
        val gate = gate(events)
        val codec =
            FakeCodec {
                Thread {
                    gate.reportFatal(FATAL_REASON, KEYFRAME_REASON)
                    errorDelivered.countDown()
                }.start()
            }

        gate.start(codec::start)
        assertTrue(errorDelivered.await(1, TimeUnit.SECONDS))
        val result = gate.commit {
            accepted.set(true)
            true
        }

        assertEquals(DecoderStartupCommitResult.Failed(FATAL_REASON), result)
        assertFalse(accepted.get())
        assertEquals(listOf("keyframe:true:$KEYFRAME_REASON", "fallback:$FATAL_REASON"), events)
    }

    @Test
    fun duplicateFatalCallbackIsDeliveredExactlyOnce() {
        val events = mutableListOf<String>()
        val gate = gate(events)

        gate.reportFatal(FATAL_REASON, KEYFRAME_REASON)
        gate.reportFatal("second_failure", "second_keyframe")
        val result = gate.commit { true }

        assertEquals(DecoderStartupCommitResult.Failed(FATAL_REASON), result)
        assertEquals(listOf("keyframe:true:$KEYFRAME_REASON", "fallback:$FATAL_REASON"), events)
    }

    @Test
    fun oldDecoderEarlyCallbackCannotAffectCommittedReplacement() {
        val oldDecoder = Any()
        val newDecoder = Any()
        var activeDecoder: Any? = oldDecoder
        var activeFailures = 0
        val isActive = { decoder: Any, generation: Long ->
            generation == SESSION_GENERATION && decoder === activeDecoder
        }
        val oldBinding = ActiveDecoderCallbackBinding(oldDecoder, SESSION_GENERATION, isActive)
        val newBinding = ActiveDecoderCallbackBinding(newDecoder, SESSION_GENERATION, isActive)
        val oldGate =
            DecoderStartupGate(
                onKeyframeRequired = { _, _ -> oldBinding.runIfActive { activeFailures++ } },
                onCodecFallbackRequired = { oldBinding.runIfActive { activeFailures++ } },
            )
        val newGate =
            DecoderStartupGate(
                onKeyframeRequired = { _, _ -> newBinding.runIfActive { activeFailures++ } },
                onCodecFallbackRequired = { newBinding.runIfActive { activeFailures++ } },
            )

        oldGate.reportFatal(FATAL_REASON, KEYFRAME_REASON)
        activeDecoder = newDecoder
        assertEquals(DecoderStartupCommitResult.Committed, newGate.commit { true })
        assertEquals(DecoderStartupCommitResult.Failed(FATAL_REASON), oldGate.commit { true })
        assertEquals(0, activeFailures)

        newGate.reportFatal(FATAL_REASON, KEYFRAME_REASON)
        assertEquals(2, activeFailures)
    }

    private fun gate(events: MutableList<String>) =
        DecoderStartupGate(
            onKeyframeRequired = { force, reason -> events += "keyframe:$force:$reason" },
            onCodecFallbackRequired = { reason -> events += "fallback:$reason" },
        )

    private class FakeCodec(
        private val startAction: () -> Unit,
    ) {
        fun start() = startAction()
    }

    private companion object {
        const val FATAL_REASON = "codec_runtime_failure"
        const val KEYFRAME_REASON = "codec error"
        const val SESSION_GENERATION = 7L
    }
}
