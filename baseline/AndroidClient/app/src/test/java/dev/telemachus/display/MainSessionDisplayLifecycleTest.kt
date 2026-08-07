package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class MainSessionDisplayLifecycleTest {
    @Test
    fun rotationOnlyDisplayChangeUpdatesGeometryAndMappingWithoutDecoderLifecycle() {
        var releases = 0
        var configurations = 0
        var geometry: StreamDisplayGeometry? = null
        val lifecycle =
            lifecycle(
                releaseDecoder = { releases++ },
                configureDecoder = { _, _, publish, completion ->
                    configurations++
                    assertTrue(publish { true })
                    completion(MainSessionDecoderConfigurationResult.Configured)
                },
                updateDisplayGeometry = { geometry = it },
            )

        lifecycle.onDisplayGeometry(StreamDisplayGeometry(1_000, 2_000, 90))

        assertEquals(0, releases)
        assertEquals(0, configurations)
        assertEquals(StreamDisplayGeometry(1_000, 2_000, 90), geometry)
        val mapped =
            TouchMapper.map(
                x = 250f,
                y = 500f,
                viewWidth = 1_000,
                viewHeight = 1_000,
                videoWidth = checkNotNull(geometry).logicalWidth,
                videoHeight = checkNotNull(geometry).logicalHeight,
            )
        assertEquals(0f, mapped.x, 0.001f)
        assertEquals(0.5f, mapped.y, 0.001f)
    }

    @Test
    fun newVideoConfigurationReleasesAndConfiguresExactlyOnce() {
        var updates = 0
        var releases = 0
        var configurations = 0
        val lifecycle =
            lifecycle(
                updateVideoConfiguration = { updates++ },
                releaseDecoder = { releases++ },
                configureDecoder = { _, _, publish, completion ->
                    configurations++
                    assertTrue(publish { true })
                    completion(MainSessionDecoderConfigurationResult.Configured)
                },
            )

        var decision: StreamVideoConfigurationDecision? = null
        lifecycle.onVideoConfiguration(StreamVideoConfiguration(1_280, 720, 0, 4)) { decision = it }

        assertEquals(1, updates)
        assertEquals(1, releases)
        assertEquals(1, configurations)
        assertEquals(StreamVideoConfigurationDecision.ACCEPTED, decision)
    }

    @Test
    fun queuedUiDoesNotCompleteBeforeDecoderConfigurationRuns() {
        val queued = mutableListOf<() -> Unit>()
        var configurations = 0
        var decision: StreamVideoConfigurationDecision? = null
        val lifecycle =
            lifecycle(
                postToUi = { queued += it },
                configureDecoder = { _, _, publish, completion ->
                    configurations++
                    assertTrue(publish { true })
                    completion(MainSessionDecoderConfigurationResult.Configured)
                },
            )

        lifecycle.onVideoConfiguration(StreamVideoConfiguration(1_920, 1_080, 0, 3)) { decision = it }

        assertEquals(1, queued.size)
        assertEquals(0, configurations)
        assertEquals(null, decision)
        queued.removeAt(0).invoke()
        assertEquals(1, configurations)
        assertEquals(null, decision)
        queued.removeAt(0).invoke()
        assertEquals(StreamVideoConfigurationDecision.ACCEPTED, decision)
    }

    @Test
    fun staleGenerationIsRejectedBeforeUiDispatch() {
        var active = false
        var queued = 0
        val lifecycle =
            lifecycle(
                isCurrentSession = { active },
                postToUi = { queued++ },
            )

        var decision: StreamVideoConfigurationDecision? = null
        lifecycle.onVideoConfiguration(StreamVideoConfiguration(1_920, 1_080, 0, 3)) { decision = it }
        lifecycle.onDisplayGeometry(StreamDisplayGeometry(1_920, 1_080, 0))

        assertEquals(0, queued)
        assertEquals(StreamVideoConfigurationDecision.reject("stale_session"), decision)
    }

    @Test
    fun disconnectBeforeQueuedUiWorkDropsDecoderAndGeometryCallbacks() {
        var active = true
        val queued = mutableListOf<() -> Unit>()
        var videoUpdates = 0
        var releases = 0
        var configurations = 0
        var geometryUpdates = 0
        val lifecycle =
            lifecycle(
                isCurrentSession = { active },
                postToUi = { queued += it },
                updateVideoConfiguration = { videoUpdates++ },
                releaseDecoder = { releases++ },
                configureDecoder = { _, _, publish, completion ->
                    configurations++
                    assertTrue(publish { true })
                    completion(MainSessionDecoderConfigurationResult.Configured)
                },
                updateDisplayGeometry = { geometryUpdates++ },
            )

        var decision: StreamVideoConfigurationDecision? = null
        lifecycle.onVideoConfiguration(StreamVideoConfiguration(1_920, 1_080, 0, 3)) { decision = it }
        lifecycle.onDisplayGeometry(StreamDisplayGeometry(1_080, 1_920, 90))
        assertEquals(2, queued.size)

        active = false
        queued.forEach { it() }

        assertEquals(0, videoUpdates)
        assertEquals(0, releases)
        assertEquals(0, configurations)
        assertEquals(0, geometryUpdates)
        assertEquals(StreamVideoConfigurationDecision.reject("stale_session"), decision)
    }

    @Test
    fun videoConfigurationWaitsForLateSurfaceThenCommitsOnce() {
        var surfaceReady = false
        var configurations = 0
        val decisions = mutableListOf<StreamVideoConfigurationDecision>()
        val lifecycle =
            lifecycle(
                configureDecoder = { _, _, publish, completion ->
                    configurations++
                    completion(
                        if (surfaceReady) {
                            assertTrue(publish { true })
                            MainSessionDecoderConfigurationResult.Configured
                        } else {
                            MainSessionDecoderConfigurationResult.RetryWhenSurfaceReady
                        },
                    )
                },
            )

        lifecycle.onVideoConfiguration(StreamVideoConfiguration(1_920, 1_080, 0, 3)) { decisions += it }

        assertTrue(lifecycle.hasPendingVideoConfiguration)
        assertEquals(1, configurations)
        assertTrue(decisions.isEmpty())

        surfaceReady = true
        lifecycle.onSurfaceReady()
        lifecycle.onSurfaceReady()

        assertFalse(lifecycle.hasPendingVideoConfiguration)
        assertEquals(2, configurations)
        assertEquals(listOf(StreamVideoConfigurationDecision.ACCEPTED), decisions)
    }

    @Test
    fun surfaceGenerationReplacementRetriesAndIgnoresOldCompletion() {
        val attempts =
            mutableListOf<
                Pair<() -> Boolean, (MainSessionDecoderConfigurationResult) -> Unit>,
            >()
        val decisions = mutableListOf<StreamVideoConfigurationDecision>()
        val lifecycle =
            lifecycle(
                configureDecoder = { _, _, publish, completion ->
                    attempts += ({ publish { true } }) to completion
                },
            )
        lifecycle.onSurfaceReady()
        lifecycle.onVideoConfiguration(StreamVideoConfiguration(1_920, 1_080, 0, 3)) { decisions += it }
        assertEquals(1, attempts.size)

        lifecycle.onSurfaceReady()
        attempts[0].second(MainSessionDecoderConfigurationResult.RetryWhenSurfaceReady)
        assertEquals(2, attempts.size)
        attempts[0].second(MainSessionDecoderConfigurationResult.Configured)
        assertTrue(decisions.isEmpty())

        assertTrue(attempts[1].first())
        attempts[1].second(MainSessionDecoderConfigurationResult.Configured)

        assertEquals(listOf(StreamVideoConfigurationDecision.ACCEPTED), decisions)
        assertFalse(lifecycle.hasPendingVideoConfiguration)
    }

    @Test
    fun surfaceReadinessTimeoutRejectsAndIgnoresLateSurfaceAndCompletion() {
        var nowNs = 0L
        var scheduledTimeout: Runnable? = null
        var configurations = 0
        var attemptCurrent: (() -> Boolean)? = null
        var publishCommit: (((() -> Boolean) -> Boolean))? = null
        var attemptCompletion: ((MainSessionDecoderConfigurationResult) -> Unit)? = null
        val decisions = mutableListOf<StreamVideoConfigurationDecision>()
        val lifecycle =
            lifecycle(
                configureDecoder = { _, isCurrent, publish, completion ->
                    configurations++
                    attemptCurrent = isCurrent
                    publishCommit = publish
                    attemptCompletion = completion
                    completion(MainSessionDecoderConfigurationResult.RetryWhenSurfaceReady)
                },
                scheduleTimeout = { task, _ -> scheduledTimeout = task },
                nowNs = { nowNs },
            )
        lifecycle.onVideoConfiguration(StreamVideoConfiguration(1_920, 1_080, 0, 3)) { decisions += it }

        nowNs = MainSessionDisplayLifecycle.DEFAULT_SURFACE_READINESS_TIMEOUT_MS * 1_000_000L
        checkNotNull(scheduledTimeout).run()
        assertFalse(checkNotNull(attemptCurrent).invoke())
        assertFalse(checkNotNull(publishCommit).invoke { true })
        lifecycle.onSurfaceReady()
        checkNotNull(attemptCompletion).invoke(MainSessionDecoderConfigurationResult.Configured)

        assertEquals(1, configurations)
        assertEquals(
            listOf(StreamVideoConfigurationDecision.reject("decoder_surface_timeout")),
            decisions,
        )
        assertFalse(lifecycle.hasPendingVideoConfiguration)
    }

    @Test
    fun slowDecoderConfigurationDoesNotConsumeSurfaceReadinessTimeout() {
        var nowNs = 0L
        var scheduledTimeouts = 0
        var publishCommit: (((() -> Boolean) -> Boolean))? = null
        var attemptCompletion: ((MainSessionDecoderConfigurationResult) -> Unit)? = null
        val decisions = mutableListOf<StreamVideoConfigurationDecision>()
        val lifecycle =
            lifecycle(
                configureDecoder = { _, _, publish, completion ->
                    publishCommit = publish
                    attemptCompletion = completion
                },
                scheduleTimeout = { _, _ -> scheduledTimeouts++ },
                nowNs = { nowNs },
            )
        lifecycle.onVideoConfiguration(StreamVideoConfiguration(1_920, 1_080, 0, 3)) { decisions += it }

        nowNs = MainSessionDisplayLifecycle.DEFAULT_SURFACE_READINESS_TIMEOUT_MS * 2_000_000L
        assertEquals(0, scheduledTimeouts)
        assertTrue(checkNotNull(publishCommit).invoke { true })
        checkNotNull(attemptCompletion).invoke(MainSessionDecoderConfigurationResult.Configured)

        assertEquals(listOf(StreamVideoConfigurationDecision.ACCEPTED), decisions)
        assertFalse(lifecycle.hasPendingVideoConfiguration)
    }

    @Test
    fun expiredProtocolCommitPreventsLateDecoderReservation() {
        val commit = TestVideoConfigurationCommit()
        var attemptCurrent: (() -> Boolean)? = null
        var publishCommit: (((() -> Boolean) -> Boolean))? = null
        var attemptCompletion: ((MainSessionDecoderConfigurationResult) -> Unit)? = null
        val lifecycle =
            lifecycle(
                configureDecoder = { _, isCurrent, publish, completion ->
                    attemptCurrent = isCurrent
                    publishCommit = publish
                    attemptCompletion = completion
                },
            )
        lifecycle.onVideoConfiguration(
            StreamVideoConfiguration(1_920, 1_080, 0, 3),
            commit,
        )

        commit.expire()
        assertFalse(checkNotNull(attemptCurrent).invoke())
        var published = false
        assertFalse(
            checkNotNull(publishCommit).invoke {
                published = true
                true
            },
        )
        assertFalse(published)
        checkNotNull(attemptCompletion).invoke(
            MainSessionDecoderConfigurationResult.Failed("stale_decoder_configuration"),
        )

        assertTrue(commit.decisions.isEmpty())
        assertFalse(lifecycle.hasPendingVideoConfiguration)
    }

    @Test
    fun legacyConfigurationSupersedesSurfaceWaitAndCommitsLatestExactlyOnce() {
        var surfaceReady = false
        var timeoutCancellations = 0
        val attempts = mutableListOf<DecoderAttempt>()
        val updatedEpochs = mutableListOf<Long>()
        var releases = 0
        val firstCommit = TestVideoConfigurationCommit(canSupersedePendingConfiguration = true)
        val latestCommit = TestVideoConfigurationCommit(canSupersedePendingConfiguration = true)
        val lifecycle =
            lifecycle(
                updateVideoConfiguration = { updatedEpochs += it.configEpoch },
                releaseDecoder = { releases++ },
                configureDecoder = { configuration, isCurrent, publish, completion ->
                    attempts += DecoderAttempt(configuration, isCurrent, publish, completion)
                    if (!surfaceReady) {
                        completion(MainSessionDecoderConfigurationResult.RetryWhenSurfaceReady)
                    }
                },
                cancelTimeout = { timeoutCancellations++ },
            )

        lifecycle.onVideoConfiguration(StreamVideoConfiguration(1_920, 1_080, 0, 3), firstCommit)
        lifecycle.onVideoConfiguration(StreamVideoConfiguration(1_280, 720, 90, 4), latestCommit)

        assertTrue(firstCommit.cancelled)
        assertTrue(firstCommit.decisions.isEmpty())
        assertFalse(attempts[0].isCurrent())
        var oldPublished = false
        assertFalse(
            attempts[0].publish {
                oldPublished = true
                true
            },
        )
        assertFalse(oldPublished)
        attempts[0].completion(MainSessionDecoderConfigurationResult.Configured)

        surfaceReady = true
        lifecycle.onSurfaceReady()
        val latestAttempt = attempts.last()
        assertEquals(4L, latestAttempt.configuration.configEpoch)
        assertTrue(latestAttempt.publish { true })
        latestAttempt.completion(MainSessionDecoderConfigurationResult.Configured)

        assertEquals(listOf(3L, 4L), updatedEpochs)
        assertEquals(2, releases)
        assertEquals(2, timeoutCancellations)
        assertEquals(listOf(StreamVideoConfigurationDecision.ACCEPTED), latestCommit.decisions)
        assertFalse(lifecycle.hasPendingVideoConfiguration)
    }

    @Test
    fun legacyConfigurationSupersedesSlowDecoderAndIgnoresLateCompletion() {
        val attempts = mutableListOf<DecoderAttempt>()
        val firstCommit = TestVideoConfigurationCommit(canSupersedePendingConfiguration = true)
        val latestCommit = TestVideoConfigurationCommit(canSupersedePendingConfiguration = true)
        val lifecycle =
            lifecycle(
                configureDecoder = { configuration, isCurrent, publish, completion ->
                    attempts += DecoderAttempt(configuration, isCurrent, publish, completion)
                },
            )

        lifecycle.onVideoConfiguration(StreamVideoConfiguration(1_920, 1_080, 0, 3), firstCommit)
        lifecycle.onVideoConfiguration(StreamVideoConfiguration(1_280, 720, 90, 4), latestCommit)

        assertEquals(listOf(3L, 4L), attempts.map { it.configuration.configEpoch })
        assertTrue(firstCommit.cancelled)
        assertFalse(attempts[0].publish { true })
        attempts[0].completion(MainSessionDecoderConfigurationResult.Configured)
        assertTrue(firstCommit.decisions.isEmpty())
        assertTrue(latestCommit.decisions.isEmpty())

        assertTrue(attempts[1].publish { true })
        attempts[1].completion(MainSessionDecoderConfigurationResult.Configured)

        assertEquals(listOf(StreamVideoConfigurationDecision.ACCEPTED), latestCommit.decisions)
        assertFalse(lifecycle.hasPendingVideoConfiguration)
    }

    @Test
    fun v1ConfigurationDoesNotSupersedePendingTransaction() {
        val attempts = mutableListOf<DecoderAttempt>()
        val firstCommit = TestVideoConfigurationCommit()
        val secondCommit = TestVideoConfigurationCommit()
        val lifecycle =
            lifecycle(
                configureDecoder = { configuration, isCurrent, publish, completion ->
                    attempts += DecoderAttempt(configuration, isCurrent, publish, completion)
                },
            )

        lifecycle.onVideoConfiguration(StreamVideoConfiguration(1_920, 1_080, 0, 3), firstCommit)
        lifecycle.onVideoConfiguration(StreamVideoConfiguration(1_280, 720, 90, 4), secondCommit)

        assertEquals(
            listOf(StreamVideoConfigurationDecision.reject("video_configuration_pending")),
            secondCommit.decisions,
        )
        assertFalse(firstCommit.cancelled)
        assertEquals(1, attempts.size)
        assertTrue(attempts.single().publish { true })
        attempts.single().completion(MainSessionDecoderConfigurationResult.Configured)
        assertEquals(listOf(StreamVideoConfigurationDecision.ACCEPTED), firstCommit.decisions)
    }

    private fun lifecycle(
        isCurrentSession: () -> Boolean = { true },
        postToUi: (() -> Unit) -> Unit = { it() },
        updateVideoConfiguration: (StreamVideoConfiguration) -> Unit = {},
        releaseDecoder: () -> Unit = {},
        configureDecoder:
            (
                StreamVideoConfiguration,
                () -> Boolean,
                (() -> Boolean) -> Boolean,
                (MainSessionDecoderConfigurationResult) -> Unit,
            ) -> Unit = { _, _, publish, completion ->
                assertTrue(publish { true })
                completion(MainSessionDecoderConfigurationResult.Configured)
            },
        updateDisplayGeometry: (StreamDisplayGeometry) -> Unit = {},
        scheduleTimeout: (Runnable, Long) -> Unit = { _, _ -> },
        cancelTimeout: (Runnable) -> Unit = {},
        nowNs: () -> Long = System::nanoTime,
    ): MainSessionDisplayLifecycle =
        MainSessionDisplayLifecycle(
            isCurrentSession = isCurrentSession,
            postToUi = postToUi,
            updateVideoConfiguration = updateVideoConfiguration,
            releaseDecoder = releaseDecoder,
            configureDecoder = configureDecoder,
            updateDisplayGeometry = updateDisplayGeometry,
            scheduleTimeout = scheduleTimeout,
            cancelTimeout = cancelTimeout,
            nowNs = nowNs,
        )

    private data class DecoderAttempt(
        val configuration: StreamVideoConfiguration,
        val isCurrent: () -> Boolean,
        val publish: (() -> Boolean) -> Boolean,
        val completion: (MainSessionDecoderConfigurationResult) -> Unit,
    )

    private class TestVideoConfigurationCommit(
        override val canSupersedePendingConfiguration: Boolean = false,
    ) : StreamVideoConfigurationCommit {
        var active = true
        var reserved = false
        var cancelled = false
        val decisions = mutableListOf<StreamVideoConfigurationDecision>()

        override fun isPending(): Boolean = active

        override fun tryPublish(publish: () -> Boolean): Boolean {
            if (!active || reserved) return false
            reserved = true
            return publish()
        }

        override fun complete(decision: StreamVideoConfigurationDecision) {
            if (!active || (decision.accepted && !reserved)) return
            active = false
            decisions += decision
        }

        fun expire() {
            active = false
        }

        override fun cancel() {
            active = false
            cancelled = true
        }
    }
}
