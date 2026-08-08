package dev.telemachus.display.internet

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class InternetVideoDecoderLifecycleTest {
    @Test
    fun missingSurfaceDefersThenRecoversWithExactlyOneAck() {
        var surfaceReady = false
        var effectCommits = 0
        var configurations = 0
        val decisions = mutableListOf<ProductVideoDecision>()
        val lifecycle =
            lifecycle(
                configureDecoder = { _, _, commit, completion ->
                    configurations++
                    if (!surfaceReady) {
                        completion(InternetDecoderConfigurationResult.RetryWhenSurfaceReady)
                    } else {
                        val decision = commit { ProductVideoDecision.ACCEPT }
                        completion(InternetDecoderConfigurationResult.Completed(decision))
                        completion(InternetDecoderConfigurationResult.Completed(decision))
                    }
                },
            )

        lifecycle.onVideoConfiguration(
            configuration(),
            effect { install ->
                effectCommits++
                install()
            },
        ) { decisions += it }

        assertTrue(lifecycle.hasPendingConfiguration)
        assertTrue(decisions.isEmpty())
        assertEquals(0, effectCommits)

        surfaceReady = true
        lifecycle.onSurfaceReady()
        lifecycle.onSurfaceReady()

        assertFalse(lifecycle.hasPendingConfiguration)
        assertEquals(2, configurations)
        assertEquals(1, effectCommits)
        assertEquals(listOf(ProductVideoDecision.ACCEPT), decisions)
    }

    @Test
    fun invalidatedSessionCancelsOldConfigurationAndLatePublish() {
        var active = true
        var attemptCurrent: (() -> Boolean)? = null
        var commitEffect: (((() -> ProductVideoDecision) -> ProductVideoDecision))? = null
        var attemptCompletion: ((InternetDecoderConfigurationResult) -> Unit)? = null
        var published = false
        val decisions = mutableListOf<ProductVideoDecision>()
        val lifecycle =
            lifecycle(
                isCurrentSession = { active },
                configureDecoder = { _, isCurrent, commit, completion ->
                    attemptCurrent = isCurrent
                    commitEffect = commit
                    attemptCompletion = completion
                },
            )

        lifecycle.onVideoConfiguration(configuration(), effect()) { decisions += it }
        active = false
        lifecycle.invalidate()

        assertFalse(checkNotNull(attemptCurrent).invoke())
        assertEquals(
            ProductVideoDecision.reject("stale_session"),
            checkNotNull(commitEffect).invoke {
                published = true
                ProductVideoDecision.ACCEPT
            },
        )
        checkNotNull(attemptCompletion).invoke(
            InternetDecoderConfigurationResult.Completed(ProductVideoDecision.ACCEPT),
        )

        assertFalse(published)
        assertEquals(listOf(ProductVideoDecision.reject("stale_session")), decisions)
        assertFalse(lifecycle.hasPendingConfiguration)
    }

    @Test
    fun surfaceWaitTimeoutFailsClosedAndIgnoresLateSurface() {
        var nowNs = 0L
        var scheduledTimeout: Runnable? = null
        var configurations = 0
        var commitEffect: (((() -> ProductVideoDecision) -> ProductVideoDecision))? = null
        var published = false
        val decisions = mutableListOf<ProductVideoDecision>()
        val lifecycle =
            lifecycle(
                configureDecoder = { _, _, commit, completion ->
                    configurations++
                    commitEffect = commit
                    completion(InternetDecoderConfigurationResult.RetryWhenSurfaceReady)
                },
                scheduleTimeout = { task, _ -> scheduledTimeout = task },
                nowNs = { nowNs },
            )

        lifecycle.onVideoConfiguration(configuration(), effect()) { decisions += it }
        nowNs = InternetVideoDecoderLifecycle.DEFAULT_SURFACE_READINESS_TIMEOUT_MS * 1_000_000L
        checkNotNull(scheduledTimeout).run()
        assertEquals(
            ProductVideoDecision.reject("stale_session"),
            checkNotNull(commitEffect).invoke {
                published = true
                ProductVideoDecision.ACCEPT
            },
        )
        lifecycle.onSurfaceReady()

        assertFalse(published)
        assertEquals(1, configurations)
        assertEquals(
            listOf(ProductVideoDecision.reject("decoder_surface_timeout")),
            decisions,
        )
        assertFalse(lifecycle.hasPendingConfiguration)
    }

    @Test
    fun queuedOldSessionConfigurationNeverStarts() {
        var active = true
        val queued = mutableListOf<() -> Unit>()
        var configurations = 0
        val decisions = mutableListOf<ProductVideoDecision>()
        val lifecycle =
            lifecycle(
                isCurrentSession = { active },
                postToUi = { queued += it },
                configureDecoder = { _, _, _, _ -> configurations++ },
            )

        lifecycle.onVideoConfiguration(configuration(), effect()) { decisions += it }
        active = false
        queued.single().invoke()

        assertEquals(0, configurations)
        assertEquals(listOf(ProductVideoDecision.reject("stale_session")), decisions)
    }

    private fun lifecycle(
        isCurrentSession: () -> Boolean = { true },
        postToUi: (() -> Unit) -> Unit = { it() },
        configureDecoder:
            (
                ProductVideoConfiguration,
                () -> Boolean,
                (() -> ProductVideoDecision) -> ProductVideoDecision,
                (InternetDecoderConfigurationResult) -> Unit,
            ) -> Unit,
        scheduleTimeout: (Runnable, Long) -> Unit = { _, _ -> },
        cancelTimeout: (Runnable) -> Unit = {},
        nowNs: () -> Long = System::nanoTime,
    ): InternetVideoDecoderLifecycle =
        InternetVideoDecoderLifecycle(
            isCurrentSession = isCurrentSession,
            postToUi = postToUi,
            configureDecoder = configureDecoder,
            scheduleTimeout = scheduleTimeout,
            cancelTimeout = cancelTimeout,
            nowNs = nowNs,
        )

    private fun configuration() =
        ProductVideoConfiguration(
            configEpoch = 3,
            codec = ProductVideoCodec.H264,
            width = 1_920,
            height = 1_080,
            framesPerSecond = 60,
            bitrateKbps = 12_000,
            streamId = 1,
            rotationDegrees = 0,
        )

    private fun effect(
        commit: ((() -> ProductVideoDecision) -> ProductVideoDecision) = { install -> install() },
    ) = ProductVideoConfigurationEffect(commit)
}
