package dev.telemachus.display

import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.atomic.AtomicReference
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class DecoderPresentationOwnerTest {
    @Test
    fun `local publish installs decoder only when renderer presentation commits`() {
        val rendererOwner = RendererOwner()
        val owner = owner(rendererOwner)
        val decoder = Any()
        val target = Any()

        val renderTarget = owner.publishRenderTarget(target)
        val attempt = attempt(surfaceToken = target, surfaceGeneration = renderTarget.generation, configEpoch = 9)

        assertTrue(owner.publishLocalDecoder(decoder, attempt))
        assertSame(decoder, owner.currentDecoder())
        assertEquals(
            RendererDecoderPresentation(configEpoch = 9, renderTargetGeneration = renderTarget.generation),
            rendererOwner.currentDecoderPresentation,
        )

        val rejectedDecoder = Any()
        val staleAttempt = attempt(surfaceToken = target, surfaceGeneration = renderTarget.generation + 1, configEpoch = 10)
        assertFalse(owner.publishLocalDecoder(rejectedDecoder, staleAttempt))
        assertSame(decoder, owner.currentDecoder())
    }

    @Test
    fun `configuration release and render target invalidation make old local attempts stale`() {
        val rendererOwner = RendererOwner()
        val owner = owner(rendererOwner)
        val target = Any()
        val renderTarget = owner.publishRenderTarget(target)
        val configuration = owner.publishLocalVideoConfiguration(width = 1280, height = 720, configEpoch = 4)
        val generation = owner.beginDecoderConfigurationAttempt()
        val attempt =
            attempt(
                surfaceToken = target,
                surfaceGeneration = renderTarget.generation,
                configurationToken = configuration,
                configurationGeneration = generation,
                configEpoch = configuration.configEpoch,
            )

        assertTrue(
            owner.isLocalAttemptCurrent(
                attempt = attempt,
                configuration = configuration,
                isSessionCurrent = { true },
                isRenderTargetUsable = { true },
            ),
        )

        val released = mutableListOf<Any>()
        owner.publishLocalDecoder(Any(), attempt)
        owner.releaseCurrentDecoder(released::add)

        assertEquals(1, released.size)
        assertFalse(
            owner.isLocalAttemptCurrent(
                attempt = attempt,
                configuration = configuration,
                isSessionCurrent = { true },
                isRenderTargetUsable = { true },
            ),
        )
        assertNull(rendererOwner.currentDecoderPresentation)
    }

    @Test
    fun `render target publish and invalidate preserve current target identity`() {
        val rendererOwner = RendererOwner()
        val owner = owner(rendererOwner)
        val firstTarget = Any()
        val secondTarget = Any()

        val first = owner.publishRenderTarget(firstTarget)
        assertSame(firstTarget, owner.currentRenderTarget())
        assertEquals(first, owner.snapshotRenderTarget(firstTarget))

        val unchanged = owner.invalidateRenderTarget(secondTarget)
        assertSame(firstTarget, owner.currentRenderTarget())
        assertEquals(first, unchanged)

        val invalidated = owner.invalidateRenderTarget(firstTarget)
        assertNull(owner.currentRenderTarget())
        assertFalse(rendererOwner.acceptsRenderTarget(firstTarget, first.generation))
        assertTrue(invalidated.generation > first.generation)
    }

    @Test
    fun `local display geometry updates through decoder presentation owner`() {
        val owner = owner()

        owner.updateLocalDisplayGeometry(StreamDisplayGeometry(logicalWidth = 1600, logicalHeight = 900, rotation = 180))

        assertEquals(1600, owner.displayWidth)
        assertEquals(900, owner.displayHeight)
        assertEquals(180, owner.displayRotation)
    }

    @Test
    fun `local frames use renderer admission and release only droppable local buffers`() {
        val rendererOwner = RendererOwner()
        val owner = owner(rendererOwner)
        val target = Any()
        val renderTarget = owner.publishRenderTarget(target)
        val decoder = Any()
        val attempt = attempt(surfaceToken = target, surfaceGeneration = renderTarget.generation, configEpoch = 5)
        val drops = mutableListOf<RendererFramePresentationDecision.Drop>()
        var decoded = 0

        owner.publishLocalDecoder(decoder, attempt)
        assertTrue(
            owner.routeLocalFrame(
                sessionCurrent = true,
                configEpoch = 5,
                decode = { decoded++ },
                onDrop = drops::add,
            ),
        )
        owner.routeLocalFrame(
            sessionCurrent = true,
            configEpoch = 4,
            decode = { fail("stale config must not decode") },
            onDrop = drops::add,
        )

        assertEquals(1, decoded)
        assertEquals(
            RendererFramePresentationDecision.Drop(RendererFrameDropReason.STALE_CONFIG_EPOCH, releaseFrame = true),
            drops.single(),
        )

        owner.releaseCurrentDecoder {}
        owner.routeLocalFrame(
            sessionCurrent = true,
            configEpoch = 5,
            decode = { fail("missing decoder must not decode") },
            onDrop = drops::add,
        )
        assertEquals(RendererFrameDropReason.DECODER_NOT_CONFIGURED, drops.last().reason)
        assertTrue(drops.last().releaseFrame)
    }

    @Test
    fun `internet frame drops are fail closed without local buffer release semantics`() {
        val rendererOwner = RendererOwner()
        val owner = owner(rendererOwner)
        val target = Any()
        val renderTarget = owner.publishRenderTarget(target)
        val decoder = Any()
        val attempt = attempt(surfaceToken = target, surfaceGeneration = renderTarget.generation, configEpoch = 12)
        var decoded = 0

        assertFalse(
            owner.routeInternetFrame(
                sessionCurrent = true,
                frameSessionEpoch = 7,
                activeSessionEpoch = 7,
                decode = { fail("missing decoder must not decode") },
            ),
        )

        assertTrue(
            owner.publishInternetDecoder(
                decoder = decoder,
                attempt = attempt,
                configuration = TestInternetVideoConfiguration(configEpoch = 12, width = 1920, height = 1080),
                displayWidth = 1920,
                displayHeight = 1080,
                displayRotation = 0,
                currentConnected = false,
                applyConnected = {},
                presentState = {},
                restoreState = {},
            ),
        )
        assertTrue(
            owner.routeInternetFrame(
                sessionCurrent = true,
                frameSessionEpoch = 7,
                activeSessionEpoch = 7,
                decode = { decoded++ },
            ),
        )
        owner.routeInternetFrame(
            sessionCurrent = true,
            frameSessionEpoch = 6,
            activeSessionEpoch = 7,
            decode = { fail("stale internet frame must not decode") },
        )

        assertEquals(1, decoded)
    }

    @Test
    fun `internet attempts require current session configuration generation and render target`() {
        val owner = owner()
        val target = Any()
        val renderTarget = owner.publishRenderTarget(target)
        val generation = owner.beginDecoderConfigurationAttempt()
        val attempt =
            attempt(
                surfaceToken = target,
                surfaceGeneration = renderTarget.generation,
                configurationGeneration = generation,
                configEpoch = 21,
            )

        assertTrue(
            owner.isInternetAttemptCurrent(
                attempt = attempt,
                isSessionCurrent = { true },
                isRenderTargetUsable = { true },
            ),
        )
        assertTrue(
            owner.canRetryInternetAttempt(
                attempt = attempt,
                isSessionCurrent = { true },
            ),
        )
        owner.beginDecoderConfigurationAttempt()
        assertFalse(
            owner.canRetryInternetAttempt(
                attempt = attempt,
                isSessionCurrent = { true },
            ),
        )
        assertFalse(
            owner.isInternetAttemptCurrent(
                attempt = attempt,
                isSessionCurrent = { true },
                isRenderTargetUsable = { true },
            ),
        )
        assertFalse(
            owner.isInternetAttemptCurrent(
                attempt = attempt,
                isSessionCurrent = { false },
                isRenderTargetUsable = { true },
            ),
        )

        owner.invalidateRenderTarget(target)
        assertFalse(
            owner.isInternetAttemptCurrent(
                attempt = attempt,
                isSessionCurrent = { true },
                isRenderTargetUsable = { true },
            ),
        )
    }

    @Test
    fun `quarantine detach leaves replaced decoder state untouched when expected is stale`() {
        val rendererOwner = RendererOwner()
        val owner = owner(rendererOwner)
        val target = Any()
        val renderTarget = owner.publishRenderTarget(target)
        val staleDecoder = Any()
        val currentDecoder = Any()
        val currentAttempt = attempt(surfaceToken = target, surfaceGeneration = renderTarget.generation, configEpoch = 31)

        assertTrue(owner.publishLocalDecoder(currentDecoder, currentAttempt))
        assertFalse(owner.detachExpectedDecoderForQuarantine(staleDecoder))

        assertSame(currentDecoder, owner.currentDecoder())
        assertEquals(
            RendererDecoderPresentation(configEpoch = 31, renderTargetGeneration = renderTarget.generation),
            rendererOwner.currentDecoderPresentation,
        )
    }

    @Test
    fun `publish internet decoder success installs decoder configuration geometry and connected state`() {
        val owner = owner()
        val target = Any()
        val renderTarget = owner.publishRenderTarget(target)
        val decoder = Any()
        val attempt = attempt(surfaceToken = target, surfaceGeneration = renderTarget.generation, configEpoch = 42)
        val connectedStates = mutableListOf<Boolean>()
        var previousState: InternetDecoderPresentationState<Any, TestInternetVideoConfiguration>? = null

        assertTrue(
            owner.publishInternetDecoder(
                decoder = decoder,
                attempt = attempt,
                configuration = TestInternetVideoConfiguration(configEpoch = 42, width = 1440, height = 900, rotation = 270),
                displayWidth = 1440,
                displayHeight = 900,
                displayRotation = 270,
                currentConnected = false,
                applyConnected = connectedStates::add,
                presentState = { previousState = it },
                restoreState = { fail("successful publish must not roll back") },
            ),
        )

        assertSame(decoder, owner.currentDecoder())
        assertEquals(42L, owner.internetConfiguration()?.configEpoch)
        assertEquals(1440, owner.displayWidth)
        assertEquals(900, owner.displayHeight)
        assertEquals(270, owner.displayRotation)
        assertEquals(listOf(true), connectedStates)
        assertEquals(false, previousState?.connected)
    }

    @Test
    fun `internet publish replaces previous internet decoder and reports previous state after commit`() {
        val rendererOwner = RendererOwner()
        val owner = owner(rendererOwner)
        val target = Any()
        val renderTarget = owner.publishRenderTarget(target)
        val firstDecoder = Any()
        val secondDecoder = Any()
        val connectedStates = mutableListOf<Boolean>()
        val released = mutableListOf<Any>()
        var firstPreviousState: InternetDecoderPresentationState<Any, TestInternetVideoConfiguration>? = null
        var secondPreviousState: InternetDecoderPresentationState<Any, TestInternetVideoConfiguration>? = null

        assertTrue(
            owner.publishInternetDecoder(
                decoder = firstDecoder,
                attempt = attempt(surfaceToken = target, surfaceGeneration = renderTarget.generation, configEpoch = 43),
                configuration = TestInternetVideoConfiguration(configEpoch = 43, width = 1280, height = 720, rotation = 0),
                displayWidth = 1280,
                displayHeight = 720,
                displayRotation = 0,
                currentConnected = false,
                applyConnected = connectedStates::add,
                presentState = { firstPreviousState = it },
                restoreState = { fail("successful publish must not roll back") },
                afterCommit = { it.decoder?.let(released::add) },
            ),
        )

        assertTrue(
            owner.publishInternetDecoder(
                decoder = secondDecoder,
                attempt = attempt(surfaceToken = target, surfaceGeneration = renderTarget.generation, configEpoch = 44),
                configuration = TestInternetVideoConfiguration(configEpoch = 44, width = 1920, height = 1080, rotation = 90),
                displayWidth = 1920,
                displayHeight = 1080,
                displayRotation = 90,
                currentConnected = true,
                applyConnected = connectedStates::add,
                presentState = { secondPreviousState = it },
                restoreState = { fail("successful replacement must not roll back") },
                afterCommit = { it.decoder?.let(released::add) },
            ),
        )

        assertNull(firstPreviousState?.decoder)
        assertSame(firstDecoder, secondPreviousState?.decoder)
        assertEquals(43L, secondPreviousState?.configuration?.configEpoch)
        assertEquals(listOf(firstDecoder), released)
        assertSame(secondDecoder, owner.currentDecoder())
        assertEquals(44L, owner.internetConfiguration()?.configEpoch)
        assertEquals(1920, owner.displayWidth)
        assertEquals(1080, owner.displayHeight)
        assertEquals(90, owner.displayRotation)
        assertEquals(
            RendererDecoderPresentation(configEpoch = 44, renderTargetGeneration = renderTarget.generation),
            rendererOwner.currentDecoderPresentation,
        )
        assertEquals(listOf(true, true), connectedStates)
    }

    @Test
    fun `internet publish holds decoder gate until presentation commit finishes`() {
        val rendererOwner = RendererOwner()
        val owner = owner(rendererOwner)
        val target = Any()
        val renderTarget = owner.publishRenderTarget(target)
        val decoder = Any()
        val attempt = attempt(surfaceToken = target, surfaceGeneration = renderTarget.generation, configEpoch = 46)
        val connectedStates = mutableListOf<Boolean>()
        val presentEntered = CountDownLatch(1)
        val allowPresent = CountDownLatch(1)
        val detachStarted = CountDownLatch(1)
        val publishResult = AtomicReference<Boolean?>()
        val publishFailure = AtomicReference<Throwable?>()
        val detachedDecoder = AtomicReference<Any?>()
        var detachThread: Thread? = null
        val expectedPresentation = RendererDecoderPresentation(configEpoch = 46, renderTargetGeneration = renderTarget.generation)
        val publishThread =
            Thread {
                try {
                    publishResult.set(
                        owner.publishInternetDecoder(
                            decoder = decoder,
                            attempt = attempt,
                            configuration = TestInternetVideoConfiguration(configEpoch = 46, width = 1920, height = 1080, rotation = 90),
                            displayWidth = 1920,
                            displayHeight = 1080,
                            displayRotation = 90,
                            currentConnected = false,
                            applyConnected = connectedStates::add,
                            presentState = {
                                presentEntered.countDown()
                                assertTrue(allowPresent.await(WAIT_TIMEOUT_SECONDS, java.util.concurrent.TimeUnit.SECONDS))
                            },
                            restoreState = { fail("successful publish must not roll back") },
                        ),
                    )
                } catch (failure: Throwable) {
                    publishFailure.set(failure)
                }
            }

        publishThread.start()
        try {
            assertTrue(presentEntered.await(WAIT_TIMEOUT_SECONDS, java.util.concurrent.TimeUnit.SECONDS))

            detachThread =
                Thread {
                    detachStarted.countDown()
                    detachedDecoder.set(owner.detachCurrentDecoder())
                }
            detachThread.start()
            assertTrue(detachStarted.await(WAIT_TIMEOUT_SECONDS, java.util.concurrent.TimeUnit.SECONDS))
            waitUntilBlockedByDecoderGate(
                thread = detachThread,
                timeoutSeconds = WAIT_TIMEOUT_SECONDS,
                operation = "competing detach",
            )

            assertEquals(expectedPresentation, rendererOwner.currentDecoderPresentation)
            assertEquals(46L, owner.internetConfiguration()?.configEpoch)
            assertEquals(1920, owner.displayWidth)
            assertEquals(1080, owner.displayHeight)
            assertEquals(90, owner.displayRotation)
            assertEquals(listOf(true), connectedStates)

            allowPresent.countDown()
            joinFinished(publishThread)
            joinFinished(detachThread)

            publishFailure.get()?.let { throw AssertionError("Internet publish failed", it) }
            assertEquals(true, publishResult.get())
            assertSame(decoder, detachedDecoder.get())
            assertNull(owner.currentDecoder())
            assertNull(rendererOwner.currentDecoderPresentation)
        } finally {
            allowPresent.countDown()
            detachThread?.let(::joinFinished)
            joinFinished(publishThread)
        }
    }

    @Test
    fun `stale internet publish after detach does not apply presentation side effects`() {
        val rendererOwner = RendererOwner()
        val owner = owner(rendererOwner)
        val target = Any()
        val renderTarget = owner.publishRenderTarget(target)
        val staleDecoder = Any()
        val staleAttempt = attempt(surfaceToken = target, surfaceGeneration = renderTarget.generation, configEpoch = 48)
        val connectedStates = mutableListOf<Boolean>()
        var presented = false

        owner.detachCurrentDecoder()

        assertFalse(
            owner.publishInternetDecoder(
                decoder = staleDecoder,
                attempt = staleAttempt,
                configuration = TestInternetVideoConfiguration(configEpoch = 48, width = 1280, height = 720, rotation = 180),
                displayWidth = 1280,
                displayHeight = 720,
                displayRotation = 180,
                currentConnected = false,
                applyConnected = connectedStates::add,
                presentState = { presented = true },
                restoreState = { fail("rejected publish must not roll back") },
            ),
        )
        assertNull(owner.currentDecoder())
        assertNull(rendererOwner.currentDecoderPresentation)
        assertNull(owner.internetConfiguration())
        assertEquals(0, owner.displayWidth)
        assertEquals(0, owner.displayHeight)
        assertEquals(0, owner.displayRotation)
        assertTrue(connectedStates.isEmpty())
        assertFalse(presented)
    }

    @Test
    fun `internet publish rejected by renderer returns false without side effects`() {
        val rendererOwner = RendererOwner()
        val owner = owner(rendererOwner)
        val target = Any()
        val renderTarget = owner.publishRenderTarget(target)
        val decoder = Any()
        val attempt = attempt(surfaceToken = target, surfaceGeneration = renderTarget.generation, configEpoch = 49)
        val connectedStates = mutableListOf<Boolean>()
        var presented = false
        var restored = false

        owner.invalidateRenderTarget(target)

        assertFalse(
            owner.publishInternetDecoder(
                decoder = decoder,
                attempt = attempt,
                configuration = TestInternetVideoConfiguration(configEpoch = 49, width = 1024, height = 768, rotation = 270),
                displayWidth = 1024,
                displayHeight = 768,
                displayRotation = 270,
                currentConnected = false,
                applyConnected = connectedStates::add,
                presentState = { presented = true },
                restoreState = { restored = true },
            ),
        )
        assertNull(owner.currentDecoder())
        assertNull(rendererOwner.currentDecoderPresentation)
        assertNull(owner.internetConfiguration())
        assertEquals(0, owner.displayWidth)
        assertEquals(0, owner.displayHeight)
        assertEquals(0, owner.displayRotation)
        assertTrue(connectedStates.isEmpty())
        assertFalse(presented)
        assertFalse(restored)
    }

    @Test
    fun `internet publish rejects connected local decoder state without side effects`() {
        val rendererOwner = RendererOwner()
        val owner = owner(rendererOwner)
        val target = Any()
        val renderTarget = owner.publishRenderTarget(target)
        val previousDecoder = Any()
        val previousAttempt = attempt(surfaceToken = target, surfaceGeneration = renderTarget.generation, configEpoch = 50)
        val previousPresentation = RendererDecoderPresentation(configEpoch = 50, renderTargetGeneration = renderTarget.generation)
        val connectedStates = mutableListOf<Boolean>()
        var presented = false
        var restored = false
        var afterCommitted = false

        assertTrue(owner.publishLocalDecoder(previousDecoder, previousAttempt))
        rendererOwner.updateDisplayGeometry(RendererDisplayGeometry(width = 800, height = 600, rotation = 0))

        assertFalse(
            owner.publishInternetDecoder(
                decoder = Any(),
                attempt = attempt(surfaceToken = target, surfaceGeneration = renderTarget.generation, configEpoch = 51),
                configuration = TestInternetVideoConfiguration(configEpoch = 51, width = 1280, height = 720, rotation = 90),
                displayWidth = 1280,
                displayHeight = 720,
                displayRotation = 90,
                currentConnected = true,
                applyConnected = connectedStates::add,
                presentState = { presented = true },
                restoreState = { restored = true },
                afterCommit = { afterCommitted = true },
            ),
        )

        assertSame(previousDecoder, owner.currentDecoder())
        assertEquals(previousPresentation, rendererOwner.currentDecoderPresentation)
        assertNull(owner.internetConfiguration())
        assertEquals(800, owner.displayWidth)
        assertEquals(600, owner.displayHeight)
        assertEquals(0, owner.displayRotation)
        assertTrue(connectedStates.isEmpty())
        assertFalse(presented)
        assertFalse(restored)
        assertFalse(afterCommitted)
    }

    @Test
    fun `release current decoder waits for in flight use and releases exactly once`() {
        val owner = owner()
        val target = Any()
        val renderTarget = owner.publishRenderTarget(target)
        val decoder = Any()
        val attempt = attempt(surfaceToken = target, surfaceGeneration = renderTarget.generation, configEpoch = 54)
        val executor = java.util.concurrent.Executors.newSingleThreadExecutor()
        val entered = java.util.concurrent.CountDownLatch(1)
        val releaseStarted = java.util.concurrent.CountDownLatch(1)
        val unblockDecode = java.util.concurrent.CountDownLatch(1)
        val released = mutableListOf<Any>()
        var releaseThread: Thread? = null

        assertTrue(owner.publishLocalDecoder(decoder, attempt))
        try {
            val decodeFuture =
                executor.submit {
                    owner.routeLocalFrame(
                        sessionCurrent = true,
                        configEpoch = 54,
                        decode = {
                            entered.countDown()
                            assertTrue(unblockDecode.await(WAIT_TIMEOUT_SECONDS, java.util.concurrent.TimeUnit.SECONDS))
                        },
                        onDrop = { fail("current frame should not drop") },
                    )
                }
            assertTrue(entered.await(WAIT_TIMEOUT_SECONDS, java.util.concurrent.TimeUnit.SECONDS))
            releaseThread =
                Thread {
                    releaseStarted.countDown()
                    owner.releaseCurrentDecoder(released::add)
                }
            releaseThread.start()
            assertTrue(releaseStarted.await(WAIT_TIMEOUT_SECONDS, java.util.concurrent.TimeUnit.SECONDS))
            waitUntilBlockedByDecoderGate(
                thread = releaseThread,
                timeoutSeconds = WAIT_TIMEOUT_SECONDS,
                operation = "competing release",
            )
            assertTrue(released.isEmpty())
            unblockDecode.countDown()
            decodeFuture.get(WAIT_TIMEOUT_SECONDS, java.util.concurrent.TimeUnit.SECONDS)
            joinFinished(releaseThread)

            owner.releaseCurrentDecoder(released::add)
            assertEquals(listOf(decoder), released)
        } finally {
            unblockDecode.countDown()
            try {
                releaseThread?.let(::joinFinished)
            } finally {
                executor.shutdownNow()
                assertTrue(executor.awaitTermination(WAIT_TIMEOUT_SECONDS, java.util.concurrent.TimeUnit.SECONDS))
            }
        }
    }

    @Test
    fun `detach keeps decoder and renderer presentation consistent against competing publish`() {
        val rendererOwner = RendererOwner()
        val target = Any()
        val firstDecoder = Any()
        val secondDecoder = Any()
        val thirdDecoder = Any()
        val executor = java.util.concurrent.Executors.newFixedThreadPool(2)
        val detachStarted = CountDownLatch(1)
        val detachEnteredRendererCleanup = CountDownLatch(1)
        val allowDetachRendererCleanup = CountDownLatch(1)
        val publishStarted = CountDownLatch(1)
        val detachedDecoder = AtomicReference<Any?>()
        val publishResult = AtomicReference<Boolean?>()
        val publishFailure = AtomicReference<Throwable?>()
        var publishThread: Thread? = null
        val hookedOwner =
            owner(
                rendererOwner = rendererOwner,
                hooks =
                    DecoderPresentationOwnerHooks(
                        beforeRendererPresentationClearDuringDetach = {
                            detachEnteredRendererCleanup.countDown()
                            assertTrue(allowDetachRendererCleanup.await(WAIT_TIMEOUT_SECONDS, java.util.concurrent.TimeUnit.SECONDS))
                        },
                    ),
            )
        val renderTarget = hookedOwner.publishRenderTarget(target)
        val firstPresentation = RendererDecoderPresentation(configEpoch = 62, renderTargetGeneration = renderTarget.generation)
        val firstAttempt = attempt(surfaceToken = target, surfaceGeneration = renderTarget.generation, configEpoch = 62)
        val secondAttempt = attempt(surfaceToken = target, surfaceGeneration = renderTarget.generation, configEpoch = 63)

        assertTrue(hookedOwner.publishLocalDecoder(firstDecoder, firstAttempt))
        assertEquals(firstPresentation, rendererOwner.currentDecoderPresentation)
        try {
            val detachFuture =
                executor.submit {
                    detachStarted.countDown()
                    detachedDecoder.set(hookedOwner.detachCurrentDecoder())
                }
            assertTrue(detachStarted.await(WAIT_TIMEOUT_SECONDS, java.util.concurrent.TimeUnit.SECONDS))
            assertTrue(detachEnteredRendererCleanup.await(WAIT_TIMEOUT_SECONDS, java.util.concurrent.TimeUnit.SECONDS))

            publishThread =
                Thread {
                    publishStarted.countDown()
                    try {
                        publishResult.set(
                            hookedOwner.publishLocalDecoder(secondDecoder, secondAttempt),
                        )
                    } catch (failure: Throwable) {
                        publishFailure.set(failure)
                    }
                }
            publishThread.start()
            assertTrue(publishStarted.await(WAIT_TIMEOUT_SECONDS, java.util.concurrent.TimeUnit.SECONDS))
            waitUntilBlockedByDecoderGate(
                thread = publishThread,
                timeoutSeconds = WAIT_TIMEOUT_SECONDS,
                operation = "competing publish",
            )

            assertEquals(firstPresentation, rendererOwner.currentDecoderPresentation)

            allowDetachRendererCleanup.countDown()
            detachFuture.get(WAIT_TIMEOUT_SECONDS, java.util.concurrent.TimeUnit.SECONDS)
            joinFinished(publishThread)

            publishFailure.get()?.let { throw AssertionError("Competing publish failed", it) }
            assertSame(firstDecoder, detachedDecoder.get())
            assertEquals(false, publishResult.get())
            assertNull(hookedOwner.currentDecoder())
            assertNull(rendererOwner.currentDecoderPresentation)

            val freshGeneration = hookedOwner.beginDecoderConfigurationAttempt()
            val freshAttempt =
                attempt(
                    surfaceToken = target,
                    surfaceGeneration = renderTarget.generation,
                    configurationGeneration = freshGeneration,
                    configEpoch = 64,
                )
            assertTrue(hookedOwner.publishLocalDecoder(thirdDecoder, freshAttempt))
            assertSame(thirdDecoder, hookedOwner.currentDecoder())
            assertEquals(
                RendererDecoderPresentation(configEpoch = 64, renderTargetGeneration = renderTarget.generation),
                rendererOwner.currentDecoderPresentation,
            )
        } finally {
            allowDetachRendererCleanup.countDown()
            try {
                publishThread?.let(::joinFinished)
            } finally {
                executor.shutdownNow()
                assertTrue(executor.awaitTermination(WAIT_TIMEOUT_SECONDS, java.util.concurrent.TimeUnit.SECONDS))
            }
        }
    }

    @Test
    fun `quarantine detach keeps decoder and renderer presentation consistent against competing publish`() {
        val rendererOwner = RendererOwner()
        val target = Any()
        val quarantinedDecoder = Any()
        val replacementDecoder = Any()
        val thirdDecoder = Any()
        val executor = java.util.concurrent.Executors.newFixedThreadPool(2)
        val detachEnteredRendererCleanup = CountDownLatch(1)
        val allowDetachRendererCleanup = CountDownLatch(1)
        val publishStarted = CountDownLatch(1)
        val quarantineResult = AtomicReference<Boolean?>()
        val publishResult = AtomicReference<Boolean?>()
        val publishFailure = AtomicReference<Throwable?>()
        var publishThread: Thread? = null
        val hookedOwner =
            owner(
                rendererOwner = rendererOwner,
                hooks =
                    DecoderPresentationOwnerHooks(
                        beforeRendererPresentationClearDuringDetach = {
                            detachEnteredRendererCleanup.countDown()
                            assertTrue(allowDetachRendererCleanup.await(WAIT_TIMEOUT_SECONDS, java.util.concurrent.TimeUnit.SECONDS))
                        },
                    ),
            )
        val renderTarget = hookedOwner.publishRenderTarget(target)
        val quarantinedPresentation = RendererDecoderPresentation(configEpoch = 72, renderTargetGeneration = renderTarget.generation)
        val quarantinedAttempt = attempt(surfaceToken = target, surfaceGeneration = renderTarget.generation, configEpoch = 72)
        val replacementAttempt = attempt(surfaceToken = target, surfaceGeneration = renderTarget.generation, configEpoch = 73)

        assertTrue(hookedOwner.publishLocalDecoder(quarantinedDecoder, quarantinedAttempt))
        assertEquals(quarantinedPresentation, rendererOwner.currentDecoderPresentation)
        try {
            val quarantineFuture =
                executor.submit {
                    quarantineResult.set(
                        hookedOwner.detachExpectedDecoderForQuarantine(quarantinedDecoder),
                    )
                }
            assertTrue(detachEnteredRendererCleanup.await(WAIT_TIMEOUT_SECONDS, java.util.concurrent.TimeUnit.SECONDS))

            publishThread =
                Thread {
                    publishStarted.countDown()
                    try {
                        publishResult.set(
                            hookedOwner.publishLocalDecoder(replacementDecoder, replacementAttempt),
                        )
                    } catch (failure: Throwable) {
                        publishFailure.set(failure)
                    }
                }
            publishThread.start()
            assertTrue(publishStarted.await(WAIT_TIMEOUT_SECONDS, java.util.concurrent.TimeUnit.SECONDS))
            waitUntilBlockedByDecoderGate(
                thread = publishThread,
                timeoutSeconds = WAIT_TIMEOUT_SECONDS,
                operation = "competing publish",
            )

            assertEquals(quarantinedPresentation, rendererOwner.currentDecoderPresentation)

            allowDetachRendererCleanup.countDown()
            quarantineFuture.get(WAIT_TIMEOUT_SECONDS, java.util.concurrent.TimeUnit.SECONDS)
            joinFinished(publishThread)

            publishFailure.get()?.let { throw AssertionError("Competing publish failed", it) }
            assertEquals(true, quarantineResult.get())
            assertEquals(false, publishResult.get())
            assertNull(hookedOwner.currentDecoder())
            assertNull(rendererOwner.currentDecoderPresentation)

            val freshGeneration = hookedOwner.beginDecoderConfigurationAttempt()
            val freshAttempt =
                attempt(
                    surfaceToken = target,
                    surfaceGeneration = renderTarget.generation,
                    configurationGeneration = freshGeneration,
                    configEpoch = 74,
                )
            assertTrue(hookedOwner.publishLocalDecoder(thirdDecoder, freshAttempt))
            assertSame(thirdDecoder, hookedOwner.currentDecoder())
            assertEquals(
                RendererDecoderPresentation(configEpoch = 74, renderTargetGeneration = renderTarget.generation),
                rendererOwner.currentDecoderPresentation,
            )
        } finally {
            allowDetachRendererCleanup.countDown()
            try {
                publishThread?.let(::joinFinished)
            } finally {
                executor.shutdownNow()
                assertTrue(executor.awaitTermination(WAIT_TIMEOUT_SECONDS, java.util.concurrent.TimeUnit.SECONDS))
            }
        }
    }

    @Test
    fun `internet presentation rolls back decoder renderer geometry and connected state atomically`() {
        val rendererOwner = RendererOwner()
        val owner = owner(rendererOwner)
        val firstTarget = Any()
        val firstSnapshot = owner.publishRenderTarget(firstTarget)
        val previousDecoder = Any()
        val previousAttempt =
            attempt(surfaceToken = firstTarget, surfaceGeneration = firstSnapshot.generation, configEpoch = 3)
        val connectedStates = mutableListOf<Boolean>()
        val released = mutableListOf<Any>()

        assertTrue(owner.publishLocalDecoder(previousDecoder, previousAttempt))
        rendererOwner.updateDisplayGeometry(RendererDisplayGeometry(width = 800, height = 600, rotation = 0))

        val nextDecoder = Any()
        val nextAttempt =
            attempt(surfaceToken = firstTarget, surfaceGeneration = firstSnapshot.generation, configEpoch = 8)
        try {
            owner.publishInternetDecoder(
                decoder = nextDecoder,
                attempt = nextAttempt,
                configuration = TestInternetVideoConfiguration(configEpoch = 8, width = 1280, height = 720, rotation = 90),
                displayWidth = 1280,
                displayHeight = 720,
                displayRotation = 90,
                currentConnected = false,
                applyConnected = connectedStates::add,
                presentState = { throw IllegalStateException("ui commit failed") },
                restoreState = {},
                afterCommit = { it.decoder?.let(released::add) },
            )
            fail("Expected presentation failure")
        } catch (failure: IllegalStateException) {
            assertEquals("ui commit failed", failure.message)
        }

        assertSame(previousDecoder, owner.currentDecoder())
        assertEquals(
            RendererDecoderPresentation(configEpoch = 3, renderTargetGeneration = firstSnapshot.generation),
            rendererOwner.currentDecoderPresentation,
        )
        assertEquals(800, owner.displayWidth)
        assertEquals(600, owner.displayHeight)
        assertEquals(0, owner.displayRotation)
        assertEquals(listOf(true, false), connectedStates)
        assertTrue(released.isEmpty())
    }

    @Test
    fun `internet rollback restores previous semantic state when renderer presentation cannot be reinstalled`() {
        val rendererOwner = RendererOwner()
        val owner = owner(rendererOwner)
        val target = Any()
        val renderTarget = owner.publishRenderTarget(target)
        val previousDecoder = Any()
        val previousAttempt = attempt(surfaceToken = target, surfaceGeneration = renderTarget.generation, configEpoch = 3)
        val previousPresentation = RendererDecoderPresentation(configEpoch = 3, renderTargetGeneration = renderTarget.generation)
        val connectedStates = mutableListOf<Boolean>()
        val released = mutableListOf<Any>()
        var restoredState: InternetDecoderPresentationState<Any, TestInternetVideoConfiguration>? = null

        assertTrue(owner.publishLocalDecoder(previousDecoder, previousAttempt))
        rendererOwner.updateDisplayGeometry(RendererDisplayGeometry(width = 800, height = 600, rotation = 0))

        val nextDecoder = Any()
        val nextAttempt = attempt(surfaceToken = target, surfaceGeneration = renderTarget.generation, configEpoch = 8)
        try {
            owner.publishInternetDecoder(
                decoder = nextDecoder,
                attempt = nextAttempt,
                configuration = TestInternetVideoConfiguration(configEpoch = 8, width = 1280, height = 720, rotation = 90),
                displayWidth = 1280,
                displayHeight = 720,
                displayRotation = 90,
                currentConnected = false,
                applyConnected = connectedStates::add,
                presentState = {
                    owner.invalidateRenderTarget(target)
                    throw IllegalStateException("ui commit failed after target invalidation")
                },
                restoreState = { restoredState = it },
                afterCommit = { it.decoder?.let(released::add) },
            )
            fail("Expected presentation failure")
        } catch (failure: IllegalStateException) {
            assertEquals("ui commit failed after target invalidation", failure.message)
        }

        assertSame(previousDecoder, owner.currentDecoder())
        assertNull(rendererOwner.currentDecoderPresentation)
        assertNull(owner.internetConfiguration())
        assertEquals(800, owner.displayWidth)
        assertEquals(600, owner.displayHeight)
        assertEquals(0, owner.displayRotation)
        assertEquals(listOf(true, false), connectedStates)
        assertSame(previousDecoder, restoredState?.decoder)
        assertNull(restoredState?.configuration)
        assertEquals(previousPresentation, restoredState?.rendererPresentation)
        assertFalse(released.contains(previousDecoder))
    }

    @Test
    fun `internet install applyConnected failure rolls back decoder renderer geometry and connected state`() {
        val rendererOwner = RendererOwner()
        val owner = owner(rendererOwner)
        val target = Any()
        val renderTarget = owner.publishRenderTarget(target)
        val previousDecoder = Any()
        val previousAttempt = attempt(surfaceToken = target, surfaceGeneration = renderTarget.generation, configEpoch = 4)
        val previousPresentation = RendererDecoderPresentation(configEpoch = 4, renderTargetGeneration = renderTarget.generation)
        val connectedStates = mutableListOf<Boolean>()
        var restoredState: InternetDecoderPresentationState<Any, TestInternetVideoConfiguration>? = null
        var applyConnectedCalls = 0

        assertTrue(owner.publishLocalDecoder(previousDecoder, previousAttempt))
        rendererOwner.updateDisplayGeometry(RendererDisplayGeometry(width = 800, height = 600, rotation = 0))

        val nextDecoder = Any()
        val nextAttempt = attempt(surfaceToken = target, surfaceGeneration = renderTarget.generation, configEpoch = 9)
        val applyFailure = IllegalStateException("connected state failed")
        val thrown =
            try {
                owner.publishInternetDecoder(
                    decoder = nextDecoder,
                    attempt = nextAttempt,
                    configuration = TestInternetVideoConfiguration(configEpoch = 9, width = 1280, height = 720, rotation = 180),
                    displayWidth = 1280,
                    displayHeight = 720,
                    displayRotation = 180,
                    currentConnected = false,
                    applyConnected = { connected ->
                        applyConnectedCalls += 1
                        connectedStates.add(connected)
                        if (applyConnectedCalls == 1) throw applyFailure
                    },
                    presentState = { fail("failed install must not present") },
                    restoreState = { restoredState = it },
                    afterCommit = { fail("failed install must not run afterCommit") },
                )
                fail("Expected connected-state failure")
                null
            } catch (failure: IllegalStateException) {
                failure
            }

        assertSame(applyFailure, thrown)
        assertSame(previousDecoder, owner.currentDecoder())
        assertEquals(previousPresentation, rendererOwner.currentDecoderPresentation)
        assertNull(owner.internetConfiguration())
        assertEquals(800, owner.displayWidth)
        assertEquals(600, owner.displayHeight)
        assertEquals(0, owner.displayRotation)
        assertEquals(listOf(true, false), connectedStates)
        assertSame(previousDecoder, restoredState?.decoder)
        assertNull(restoredState?.configuration)
        assertEquals(previousPresentation, restoredState?.rendererPresentation)
    }

    @Test
    fun `owner source stays independent of android ui transport protocol and codec layers`() {
        val source = repositorySource(PRODUCTION_DECODER_PRESENTATION_OWNER)

        FORBIDDEN_OWNER_REFERENCES.forEach { reference ->
            assertFalse(
                "DecoderPresentationOwner must not depend on `$reference`",
                source.contains(reference),
            )
        }
    }

    private fun owner(
        rendererOwner: RendererOwner = RendererOwner(),
        hooks: DecoderPresentationOwnerHooks = DecoderPresentationOwnerHooks(),
    ) =
        DecoderPresentationOwner<Any, TestInternetVideoConfiguration>(
            rendererOwner = rendererOwner,
            internetConfigurationEpoch = { it.configEpoch },
            hooks = hooks,
        )

    private fun attempt(
        surfaceToken: Any = SURFACE_TOKEN,
        surfaceGeneration: Long = 11L,
        configurationToken: Any = CONFIGURATION_TOKEN,
        configurationGeneration: Long = 0L,
        configEpoch: Long = 17L,
    ) = DecoderLifecycleAttempt(
        sessionToken = SESSION_TOKEN,
        sessionGeneration = 19L,
        surfaceToken = surfaceToken,
        surfaceGeneration = surfaceGeneration,
        configurationToken = configurationToken,
        configurationGeneration = configurationGeneration,
        configEpoch = configEpoch,
        codec = StreamCodec.HEVC,
        failSessionOnFailure = false,
        isConfigurationCurrent = { true },
    )

    private fun repositorySource(relativePath: String): String {
        var current = File(requireNotNull(System.getProperty("user.dir"))).canonicalFile
        repeat(8) {
            listOf(relativePath, "baseline/AndroidClient/$relativePath")
                .map(current::resolve)
                .firstOrNull(File::isFile)
                ?.let { return it.readText() }
            current = current.parentFile?.canonicalFile ?: current
        }
        error("$relativePath not found from " + System.getProperty("user.dir"))
    }

    private fun joinFinished(thread: Thread) {
        thread.join(java.util.concurrent.TimeUnit.SECONDS.toMillis(WAIT_TIMEOUT_SECONDS))
        assertFalse(thread.isAlive)
    }

    private data class TestInternetVideoConfiguration(
        val configEpoch: Long,
        val width: Int,
        val height: Int,
        val rotation: Int = 0,
    )

    private companion object {
        const val PRODUCTION_DECODER_PRESENTATION_OWNER =
            "app/src/main/java/dev/telemachus/display/DecoderPresentationOwner.kt"
        const val WAIT_TIMEOUT_SECONDS = 5L
        val SESSION_TOKEN = Any()
        val SURFACE_TOKEN = Any()
        val CONFIGURATION_TOKEN = Any()
        val FORBIDDEN_OWNER_REFERENCES =
            listOf(
                "import android.",
                "import androidx.",
                "MainActivity",
                "VideoDecoder",
                "MediaCodec",
                "StreamClient",
                "StreamTransportOwner",
                "SocketStreamTransportConnection",
                "java.net.Socket",
                "ProtocolV1Session",
                "InternetProductSession",
                "SurfaceHolder",
            )
    }
}
