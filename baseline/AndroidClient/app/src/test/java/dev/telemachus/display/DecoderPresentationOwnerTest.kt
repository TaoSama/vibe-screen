package dev.telemachus.display

import java.io.File
import java.util.concurrent.CountDownLatch
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

        assertTrue(owner.publishLocalDecoder(decoder, attempt))
        try {
            val decodeFuture =
                executor.submit {
                    owner.routeLocalFrame(
                        sessionCurrent = true,
                        configEpoch = 54,
                        decode = {
                            entered.countDown()
                            assertTrue(unblockDecode.await(1, java.util.concurrent.TimeUnit.SECONDS))
                        },
                        onDrop = { fail("current frame should not drop") },
                    )
                }
            assertTrue(entered.await(1, java.util.concurrent.TimeUnit.SECONDS))
            val releaseThread =
                Thread {
                    releaseStarted.countDown()
                    owner.releaseCurrentDecoder(released::add)
                }
            releaseThread.start()
            assertTrue(releaseStarted.await(1, java.util.concurrent.TimeUnit.SECONDS))
            Thread.sleep(50)
            assertTrue(released.isEmpty())
            unblockDecode.countDown()
            decodeFuture.get(1, java.util.concurrent.TimeUnit.SECONDS)
            releaseThread.join(1_000)

            owner.releaseCurrentDecoder(released::add)
            assertEquals(listOf(decoder), released)
        } finally {
            unblockDecode.countDown()
            executor.shutdownNow()
        }
    }

    @Test
    fun `detach waits for in flight decoder gate before clearing renderer presentation`() {
        val rendererOwner = RendererOwner()
        val owner = owner(rendererOwner)
        val target = Any()
        val renderTarget = owner.publishRenderTarget(target)
        val decoder = Any()
        val presentation = RendererDecoderPresentation(configEpoch = 62, renderTargetGeneration = renderTarget.generation)
        val attempt = attempt(surfaceToken = target, surfaceGeneration = renderTarget.generation, configEpoch = 62)
        val executor = java.util.concurrent.Executors.newSingleThreadExecutor()
        val decodeEntered = CountDownLatch(1)
        val releaseDecode = CountDownLatch(1)
        val detachStarted = CountDownLatch(1)
        val detachFinished = CountDownLatch(1)
        val detachedDecoder = java.util.concurrent.atomic.AtomicReference<Any?>()

        assertTrue(owner.publishLocalDecoder(decoder, attempt))
        assertEquals(presentation, rendererOwner.currentDecoderPresentation)
        try {
            val frameFuture =
                executor.submit {
                    owner.routeLocalFrame(
                        sessionCurrent = true,
                        configEpoch = 62,
                        decode = {
                            decodeEntered.countDown()
                            assertTrue(releaseDecode.await(1, java.util.concurrent.TimeUnit.SECONDS))
                        },
                        onDrop = { fail("current frame should not drop") },
                    )
                }
            assertTrue(decodeEntered.await(1, java.util.concurrent.TimeUnit.SECONDS))

            val detachThread =
                Thread {
                    detachStarted.countDown()
                    detachedDecoder.set(owner.detachCurrentDecoder())
                    detachFinished.countDown()
                }
            detachThread.start()
            assertTrue(detachStarted.await(1, java.util.concurrent.TimeUnit.SECONDS))
            waitUntilBlocked(detachThread)

            assertEquals(presentation, rendererOwner.currentDecoderPresentation)
            assertFalse(detachFinished.await(50, java.util.concurrent.TimeUnit.MILLISECONDS))

            releaseDecode.countDown()
            frameFuture.get(1, java.util.concurrent.TimeUnit.SECONDS)
            detachThread.join(1_000)

            assertSame(decoder, detachedDecoder.get())
            assertNull(rendererOwner.currentDecoderPresentation)
            assertNull(owner.currentDecoder())
        } finally {
            releaseDecode.countDown()
            executor.shutdownNow()
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

    private fun owner(rendererOwner: RendererOwner = RendererOwner()) =
        DecoderPresentationOwner<Any, TestInternetVideoConfiguration>(
            rendererOwner = rendererOwner,
            internetConfigurationEpoch = { it.configEpoch },
        )

    private fun attempt(
        surfaceToken: Any = SURFACE_TOKEN,
        surfaceGeneration: Long = 11L,
        configurationToken: Any = CONFIGURATION_TOKEN,
        configurationGeneration: Long = 13L,
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

    private fun waitUntilBlocked(thread: Thread) {
        val deadline = System.nanoTime() + java.util.concurrent.TimeUnit.SECONDS.toNanos(1)
        while (System.nanoTime() < deadline) {
            if (thread.state == Thread.State.BLOCKED) return
            Thread.sleep(10)
        }
        fail("Expected detach to wait for the in-flight decoder use")
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
