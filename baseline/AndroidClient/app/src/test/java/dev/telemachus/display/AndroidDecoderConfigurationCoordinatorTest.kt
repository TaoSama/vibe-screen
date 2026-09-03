package dev.telemachus.display

import java.util.concurrent.atomic.AtomicReference
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

class AndroidDecoderConfigurationCoordinatorTest {
    @Test
    fun localStaleSessionFailsWithoutCreatingDecoder() {
        val fixture = Fixture()
        var created = false

        fixture.coordinator.configureLocal(
            request = fixture.localRequest(session = null),
            createDecoder = { created = true; Any() },
        ) { result ->
            assertEquals(AndroidDecoderConfigurationResult.Failed("stale_session"), result)
        }

        assertFalse(created)
    }

    @Test
    fun localStaleSessionGenerationFails() {
        val fixture = Fixture()
        var created = false

        fixture.coordinator.configureLocal(
            request = fixture.localRequest(isSessionCurrent = { _, _ -> false }),
            createDecoder = { created = true; Any() },
        ) { result ->
            assertEquals(AndroidDecoderConfigurationResult.Failed("stale_session"), result)
        }

        assertFalse(created)
    }

    @Test
    fun localMissingConfigurationFails() {
        val fixture = Fixture()
        var created = false

        fixture.coordinator.configureLocal(
            request = fixture.localRequest(configuration = null),
            createDecoder = { created = true; Any() },
        ) { result ->
            assertEquals(AndroidDecoderConfigurationResult.Failed("stale_video_configuration"), result)
        }

        assertFalse(created)
    }

    @Test
    fun localStaleConfigurationEpochFails() {
        val fixture = Fixture()
        var created = false

        fixture.coordinator.configureLocal(
            request = fixture.localRequest(expectedConfigEpoch = 99L),
            createDecoder = { created = true; Any() },
        ) { result ->
            assertEquals(AndroidDecoderConfigurationResult.Failed("stale_video_configuration"), result)
        }

        assertFalse(created)
    }

    @Test
    fun localMissingSurfaceGenerationRetries() {
        val fixture = Fixture()
        var created = false

        fixture.coordinator.configureLocal(
            request = fixture.localRequest(renderTargetGeneration = null),
            createDecoder = { created = true; Any() },
        ) { result ->
            assertEquals(AndroidDecoderConfigurationResult.RetryWhenSurfaceReady, result)
        }

        assertFalse(created)
    }

    @Test
    fun localSuccessfulConfigurationPublishesAndInvokesOnConfigured() {
        val fixture = Fixture()
        val decoder = Any()
        val onConfigured = AtomicReference<Any?>()
        var published = false

        fixture.coordinator.configureLocal(
            request =
                fixture.localRequest(
                    publishConfigurationCommit = { publish ->
                        published = true
                        publish()
                    },
                    onConfigured = { onConfigured.set(it) },
                ),
            createDecoder = { decoder },
        ) { result ->
            assertEquals(AndroidDecoderConfigurationResult.Configured, result)
        }

        assertTrue(published)
        assertSame(decoder, onConfigured.get())
        assertSame(decoder, fixture.decoderPresentationOwner.currentDecoder())
    }

    @Test
    fun localCreateFailureReportsFailure() {
        val fixture = Fixture()
        val failure = DecoderInitializationException(
            DecoderFailure(DecoderFailureKind.STRUCTURAL_TARGET_UNSUPPORTED, STRUCTURAL_HEVC_TARGET_UNSUPPORTED_REASON),
        )

        fixture.coordinator.configureLocal(
            request = fixture.localRequest(),
            createDecoder = { throw failure },
        ) { result ->
            assertEquals(
                AndroidDecoderConfigurationResult.Failed(STRUCTURAL_HEVC_TARGET_UNSUPPORTED_REASON),
                result,
            )
        }

        assertEquals(1, fixture.structuralFailures.size)
    }

    @Test
    fun localCommitRejectionFailsWithStaleReason() {
        val fixture = Fixture()
        val decoder = Any()

        fixture.coordinator.configureLocal(
            request =
                fixture.localRequest(
                    publishConfigurationCommit = { _ ->
                        DecoderConfigurationCommitDecision.reject("stale_decoder_configuration")
                    },
                ),
            createDecoder = { decoder },
        ) { result ->
            assertEquals(
                AndroidDecoderConfigurationResult.Failed("stale_decoder_configuration"),
                result,
            )
        }

        assertNull(fixture.decoderPresentationOwner.currentDecoder())
        assertEquals(listOf(decoder), fixture.releasedDecoders)
    }

    @Test
    fun localOnConfiguredFailureDoesNotDoubleFailCompletion() {
        val fixture = Fixture()
        val decoder = Any()
        var completionCount = 0

        fixture.coordinator.configureLocal(
            request =
                fixture.localRequest(
                    onConfigured = { throw IllegalStateException("onConfigured boom") },
                ),
            createDecoder = { decoder },
        ) { result ->
            completionCount++
            assertEquals(AndroidDecoderConfigurationResult.Configured, result)
        }

        assertEquals(1, completionCount)
    }

    @Test
    fun internetUnsupportedCodecFailsBeforeDecoderCreation() {
        val fixture = Fixture()
        var created = false

        fixture.coordinator.configureInternet(
            request = fixture.internetRequest(unsupportedCodecReason = "av1_decoder_unavailable"),
            createDecoder = { created = true; Any() },
        ) { result ->
            assertEquals(AndroidDecoderConfigurationResult.Failed("av1_decoder_unavailable"), result)
        }

        assertFalse(created)
    }

    @Test
    fun internetStaleSessionFails() {
        val fixture = Fixture()
        var created = false

        fixture.coordinator.configureInternet(
            request = fixture.internetRequest(session = null),
            createDecoder = { created = true; Any() },
        ) { result ->
            assertEquals(AndroidDecoderConfigurationResult.Failed("stale_session"), result)
        }

        assertFalse(created)
    }

    @Test
    fun internetStaleSessionGenerationFails() {
        val fixture = Fixture()
        var created = false

        fixture.coordinator.configureInternet(
            request = fixture.internetRequest(isSessionCurrent = { false }),
            createDecoder = { created = true; Any() },
        ) { result ->
            assertEquals(AndroidDecoderConfigurationResult.Failed("stale_session"), result)
        }

        assertFalse(created)
    }

    @Test
    fun internetMissingSurfaceRetries() {
        val fixture = Fixture()
        var created = false

        fixture.coordinator.configureInternet(
            request = fixture.internetRequest(renderTargetGeneration = null),
            createDecoder = { created = true; Any() },
        ) { result ->
            assertEquals(AndroidDecoderConfigurationResult.RetryWhenSurfaceReady, result)
        }

        assertFalse(created)
    }

    @Test
    fun internetUnusableSurfaceRetries() {
        val fixture = Fixture()
        var created = false

        fixture.coordinator.configureInternet(
            request = fixture.internetRequest(isRenderTargetUsable = { false }),
            createDecoder = { created = true; Any() },
        ) { result ->
            assertEquals(AndroidDecoderConfigurationResult.RetryWhenSurfaceReady, result)
        }

        assertFalse(created)
    }

    @Test
    fun internetSuccessfulConfigurationPublishesAndReplacesActiveDecoder() {
        val fixture = Fixture()
        val decoder = Any()
        var presentCalled = false

        fixture.coordinator.configureInternet(
            request =
                fixture.internetRequest(
                    presentState = { presentCalled = true },
                    publishConfigurationCommit = { publish -> publish() },
                ),
            createDecoder = { decoder },
        ) { result ->
            assertEquals(AndroidDecoderConfigurationResult.Configured, result)
        }

        assertTrue(presentCalled)
        assertSame(decoder, fixture.decoderPresentationOwner.currentDecoder())
    }

    @Test
    fun internetCreateFailureReportsFailure() {
        val fixture = Fixture()
        val failure = DecoderInitializationException(
            DecoderFailure(DecoderFailureKind.STRUCTURAL_TARGET_UNSUPPORTED, STRUCTURAL_HEVC_TARGET_UNSUPPORTED_REASON),
        )

        fixture.coordinator.configureInternet(
            request = fixture.internetRequest(),
            createDecoder = { throw failure },
        ) { result ->
            assertEquals(
                AndroidDecoderConfigurationResult.Failed(STRUCTURAL_HEVC_TARGET_UNSUPPORTED_REASON),
                result,
            )
        }

        assertEquals(1, fixture.structuralFailures.size)
    }

    @Test
    fun internetCommitRejectionFailsWithRejectionReason() {
        val fixture = Fixture()

        fixture.coordinator.configureInternet(
            request =
                fixture.internetRequest(
                    publishConfigurationCommit = { _ ->
                        DecoderConfigurationCommitDecision.reject("stale_decoder_configuration")
                    },
                ),
            createDecoder = { Any() },
        ) { result ->
            assertEquals(
                AndroidDecoderConfigurationResult.Failed("stale_decoder_configuration"),
                result,
            )
        }
    }

    @Test
    fun decoderCreationCallbacksOnlyRunWhenDecoderIsActive() {
        val fixture = Fixture()
        val decoder = Any()
        val otherDecoder = Any()
        var keyframeCalls = 0
        var codecFailureCalls = 0
        lateinit var callbacks: DecoderCreationCallbacks<Any>

        fixture.coordinator.configureLocal(
            request =
                fixture.localRequest(
                    publishConfigurationCommit = { publish -> publish() },
                ),
            createDecoder = { cb ->
                callbacks = cb
                decoder
            },
        ) { }

        callbacks.onKeyframeRequired(decoder, true, "test") { _, _ -> keyframeCalls++ }
        callbacks.onCodecFailure(
            decoder,
            DecoderFailure(DecoderFailureKind.SESSION_RUNTIME_FAILURE, "runtime"),
        ) { _, _ -> codecFailureCalls++ }

        assertEquals(1, keyframeCalls)
        assertEquals(1, codecFailureCalls)
        assertEquals(1, fixture.structuralFailures.size)

        callbacks.onKeyframeRequired(otherDecoder, true, "stale") { _, _ -> keyframeCalls++ }
        callbacks.onCodecFailure(
            otherDecoder,
            DecoderFailure(DecoderFailureKind.SESSION_RUNTIME_FAILURE, "stale"),
        ) { _, _ -> codecFailureCalls++ }

        assertEquals(1, keyframeCalls)
        assertEquals(1, codecFailureCalls)
    }

    @Test
    fun frameDecodedCallbackReleasesBufferWithoutActiveDecoderGateOrUiDispatch() {
        var ownerThreadPosts = 0
        val fixture = Fixture(
            postCommit = { action ->
                ownerThreadPosts++
                action()
            },
        )
        val decoder = Any()
        lateinit var callbacks: DecoderCreationCallbacks<Any>

        fixture.coordinator.configureLocal(
            request =
                fixture.localRequest(
                    publishConfigurationCommit = { publish -> publish() },
                ),
            createDecoder = { cb ->
                callbacks = cb
                decoder
            },
        ) { result ->
            assertEquals(AndroidDecoderConfigurationResult.Configured, result)
        }

        fixture.decoderPresentationOwner.detachExpectedDecoderForQuarantine(decoder)
        val frame = byteArrayOf(1, 2, 3)
        var releasedFrame: ByteArray? = null

        callbacks.onFrameDecoded(frame) { releasedFrame = it }

        assertSame(frame, releasedFrame)
        assertEquals(1, ownerThreadPosts)
    }

    private class Fixture(
        postCommit: (() -> Unit) -> Unit = { it() },
    ) {
        val decoderPresentationOwner =
            DecoderPresentationOwner<Any, TestInternetConfiguration>(
                rendererOwner = RendererOwner(),
                internetConfigurationEpoch = { it.configEpoch },
            )
        val structuralFailures = mutableListOf<Pair<StreamCodec, DecoderFailure>>()
        val releasedDecoders = mutableListOf<Any>()
        val coordinator =
            AndroidDecoderConfigurationCoordinator<Any, TestInternetConfiguration>(
                decoderPresentationOwner = decoderPresentationOwner,
                executeDecoderWork = { it() },
                postCommit = postCommit,
                updateScaleMode = { },
                commitStartup = { _, publish ->
                    if (publish()) DecoderStartupCommitResult.Committed
                    else DecoderStartupCommitResult.NotCommitted
                },
                releaseDecoder = { releasedDecoders.add(it) },
                recordStructuralFailure = { codec, failure, _ ->
                    structuralFailures.add(codec to failure)
                    true
                },
            )

        private val session = Any()
        private val renderTarget = Any()
        private val configuration: EncodedVideoConfigurationSnapshot

        init {
            decoderPresentationOwner.publishRenderTarget(renderTarget)
            configuration = decoderPresentationOwner.publishLocalVideoConfiguration(
                width = 1280,
                height = 720,
                configEpoch = 42L,
            )
        }

        fun localRequest(
            session: Any? = this.session,
            sessionGeneration: Long = 1L,
            renderTarget: Any = this.renderTarget,
            renderTargetGeneration: Long? = decoderPresentationOwner.snapshotRenderTarget(renderTarget)?.generation,
            configuration: EncodedVideoConfigurationSnapshot? = this.configuration,
            expectedConfigEpoch: Long = this.configuration.configEpoch,
            codec: StreamCodec = StreamCodec.HEVC,
            failSessionOnFailure: Boolean = false,
            isSessionCurrent: (Any, Long) -> Boolean = { _, _ -> true },
            isRenderTargetUsable: () -> Boolean = { true },
            isConfigurationCurrent: () -> Boolean = { true },
            publishConfigurationCommit: ((() -> DecoderConfigurationCommitDecision) -> DecoderConfigurationCommitDecision) =
                { publish -> publish() },
            reportInitializationFailure: (Exception, Boolean) -> Unit = { _, _ -> },
            onConfigured: (Any) -> Unit = { },
        ) = LocalDecoderConfigurationRequest(
            session = session,
            sessionGeneration = sessionGeneration,
            renderTarget = renderTarget,
            renderTargetGeneration = renderTargetGeneration,
            configuration = configuration,
            expectedConfigEpoch = expectedConfigEpoch,
            codec = codec,
            failSessionOnFailure = failSessionOnFailure,
            isSessionCurrent = isSessionCurrent,
            isRenderTargetUsable = isRenderTargetUsable,
            isConfigurationCurrent = isConfigurationCurrent,
            publishConfigurationCommit = publishConfigurationCommit,
            reportInitializationFailure = reportInitializationFailure,
            onConfigured = onConfigured,
        )

        fun internetRequest(
            session: Any? = this.session,
            sessionGeneration: Long = 1L,
            renderTarget: Any = this.renderTarget,
            renderTargetGeneration: Long? = decoderPresentationOwner.snapshotRenderTarget(renderTarget)?.generation,
            configuration: TestInternetConfiguration = TestInternetConfiguration(configEpoch = 42L, width = 1280, height = 720, rotationDegrees = 0),
            configEpoch: Long = configuration.configEpoch,
            codec: StreamCodec = StreamCodec.HEVC,
            unsupportedCodecReason: String? = null,
            displayWidth: Int = configuration.width,
            displayHeight: Int = configuration.height,
            displayRotation: Int = configuration.rotationDegrees,
            currentConnected: Boolean = false,
            applyConnected: (Boolean) -> Unit = { },
            presentState: (InternetDecoderPresentationState<Any, TestInternetConfiguration>) -> Unit = { },
            restoreState: (InternetDecoderPresentationState<Any, TestInternetConfiguration>) -> Unit = { },
            afterCommit: (InternetDecoderPresentationState<Any, TestInternetConfiguration>) -> Unit = { },
            isSessionCurrent: () -> Boolean = { true },
            isRenderTargetUsable: () -> Boolean = { true },
            isConfigurationCurrent: () -> Boolean = { true },
            publishConfigurationCommit: ((() -> DecoderConfigurationCommitDecision) -> DecoderConfigurationCommitDecision) =
                { publish -> publish() },
            reportInitializationFailure: (Exception, Boolean) -> Unit = { _, _ -> },
        ) = InternetDecoderConfigurationRequest(
            session = session,
            sessionGeneration = sessionGeneration,
            renderTarget = renderTarget,
            renderTargetGeneration = renderTargetGeneration,
            configuration = configuration,
            configEpoch = configEpoch,
            codec = codec,
            unsupportedCodecReason = unsupportedCodecReason,
            displayWidth = displayWidth,
            displayHeight = displayHeight,
            displayRotation = displayRotation,
            currentConnected = currentConnected,
            applyConnected = applyConnected,
            presentState = presentState,
            restoreState = restoreState,
            afterCommit = afterCommit,
            isSessionCurrent = isSessionCurrent,
            isRenderTargetUsable = isRenderTargetUsable,
            isConfigurationCurrent = isConfigurationCurrent,
            publishConfigurationCommit = publishConfigurationCommit,
            reportInitializationFailure = reportInitializationFailure,
        )
    }

    private data class TestInternetConfiguration(
        val configEpoch: Long,
        val width: Int,
        val height: Int,
        val rotationDegrees: Int,
    )
}
