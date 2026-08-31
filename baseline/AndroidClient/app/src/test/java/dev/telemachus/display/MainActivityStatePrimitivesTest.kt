package dev.telemachus.display

import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class MainActivityStatePrimitivesTest {
    @Test
    fun encodedVideoConfigurationPublishesOneCrossThreadSnapshot() {
        val state = EncodedVideoConfigurationState()
        val executor = Executors.newSingleThreadExecutor()
        try {
            val first = state.publish(width = 1280, height = 720, configEpoch = 11L)
            val observedFirst =
                executor.submit<EncodedVideoConfigurationSnapshot?> { state.snapshot() }
                    .get(1, TimeUnit.SECONDS)

            assertSame(first, observedFirst)
            assertEquals(1280, observedFirst?.width)
            assertEquals(720, observedFirst?.height)
            assertEquals(11L, observedFirst?.configEpoch)

            val second =
                executor.submit<EncodedVideoConfigurationSnapshot> {
                    state.publish(width = 1920, height = 1080, configEpoch = 12L)
                }.get(1, TimeUnit.SECONDS)

            assertSame(second, state.snapshot())
            assertFalse(state.isCurrent(first))
            assertTrue(state.isCurrent(second))

            state.clear()
            assertNull(state.snapshot())
        } finally {
            executor.shutdownNow()
        }
    }

    @Test
    fun presentationFailureRestoresCompletePreviousSemanticState() {
        val previous = presentationState("old-decoder", "old-config", 1280, 720, 90, connected = true)
        val attempted = presentationState("new-decoder", "new-config", 1920, 1080, 270, connected = true)
        var current = previous
        val presentationFailure = IllegalStateException("presentation failed")

        val thrown =
            try {
                commitInternetDecoderPresentation(
                    nextState = attempted,
                    captureState = { current },
                    installState = { current = it; true },
                    restoreState = { attemptedState, previousState ->
                        assertEquals(attempted, attemptedState)
                        assertEquals(previous, previousState)
                        current = previousState
                    },
                ) { capturedPrevious ->
                    assertEquals(previous, capturedPrevious)
                    assertEquals(attempted, current)
                    throw presentationFailure
                }
                fail("Expected presentation failure")
                null
            } catch (failure: IllegalStateException) {
                failure
            }

        assertSame(presentationFailure, thrown)
        assertEquals(previous, current)
    }

    @Test
    fun successfulPresentationKeepsNewStateAndReturnsPreviousState() {
        val previous = presentationState("old-decoder", "old-config", 1280, 720, 0, connected = false)
        val attempted = presentationState("new-decoder", "new-config", 1920, 1080, 90, connected = true)
        var current = previous
        var rollbackCalled = false

        val captured =
            commitInternetDecoderPresentation(
                nextState = attempted,
                captureState = { current },
                installState = { current = it; true },
                restoreState = { _, _ -> rollbackCalled = true },
            ) { capturedPrevious ->
                assertEquals(previous, capturedPrevious)
                assertEquals(attempted, current)
            }

        assertEquals(previous, captured)
        assertEquals(attempted, current)
        assertFalse(rollbackCalled)
    }

    @Test
    fun rejectedPresentationInstallDoesNotRunPresenterOrRollback() {
        val previous = presentationState("old-decoder", "old-config", 1280, 720, 0, connected = true)
        val attempted = presentationState("new-decoder", "new-config", 1920, 1080, 90, connected = true)
        var current = previous
        var presenterCalled = false
        var rollbackCalled = false

        val captured =
            commitInternetDecoderPresentation(
                nextState = attempted,
                captureState = { current },
                installState = { false },
                restoreState = { _, _ -> rollbackCalled = true },
            ) {
                presenterCalled = true
            }

        assertNull(captured)
        assertEquals(previous, current)
        assertFalse(presenterCalled)
        assertFalse(rollbackCalled)
    }

    @Test
    fun rollbackFailureIsSuppressedWithoutMaskingPresentationFailure() {
        val previous = presentationState("old-decoder", "old-config", 1280, 720, 0, connected = true)
        val attempted = presentationState("new-decoder", "new-config", 1920, 1080, 90, connected = true)
        var current = previous
        val presentationFailure = IllegalStateException("presentation failed")
        val rollbackFailure = IllegalArgumentException("rollback failed")

        val thrown =
            try {
                commitInternetDecoderPresentation(
                    nextState = attempted,
                    captureState = { current },
                    installState = { current = it; true },
                    restoreState = { _, _ -> throw rollbackFailure },
                ) { throw presentationFailure }
                fail("Expected presentation failure")
                null
            } catch (failure: IllegalStateException) {
                failure
            }

        assertSame(presentationFailure, thrown)
        assertEquals(listOf(rollbackFailure), thrown?.suppressed?.toList())
        assertEquals(attempted, current)
    }

    private fun presentationState(
        decoder: String,
        configuration: String,
        width: Int,
        height: Int,
        rotation: Int,
        connected: Boolean,
    ) =
        InternetDecoderPresentationState(
            decoder = decoder,
            configuration = configuration,
            rendererPresentation = null,
            displayWidth = width,
            displayHeight = height,
            displayRotation = rotation,
            connected = connected,
        )
}
