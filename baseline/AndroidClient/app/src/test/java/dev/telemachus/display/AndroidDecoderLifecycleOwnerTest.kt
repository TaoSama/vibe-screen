package dev.telemachus.display

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class AndroidDecoderLifecycleOwnerTest {
    @Test
    fun admissionStartsOnlyWhenSurfaceSessionAndConfigurationAreCurrent() {
        val port = FakePort()
        val owner = AndroidDecoderLifecycleOwner(port)
        val attempt = attempt()

        assertEquals(DecoderLifecycleAttemptAdmission.Start, owner.admitAttempt(attempt))

        port.activeDecoder = Any()
        assertEquals(DecoderLifecycleAttemptAdmission.RetryWhenSurfaceReady, owner.admitAttempt(attempt))

        port.canRetry = false
        assertEquals(
            DecoderLifecycleAttemptAdmission.Failed(STALE_DECODER_CONFIGURATION),
            owner.admitAttempt(attempt),
        )

        port.activeDecoder = null
        port.canRetry = true
        port.current = false
        assertEquals(DecoderLifecycleAttemptAdmission.RetryWhenSurfaceReady, owner.admitAttempt(attempt))

        port.canRetry = false
        assertEquals(
            DecoderLifecycleAttemptAdmission.Failed(STALE_DECODER_CONFIGURATION),
            owner.admitAttempt(attempt),
        )
    }

    @Test
    fun admissionAllowsActiveReplacementForOptInInternetAttempts() {
        val port = FakePort(activeDecoder = Any())
        val owner = AndroidDecoderLifecycleOwner(port)

        assertEquals(
            DecoderLifecycleAttemptAdmission.Start,
            owner.admitAttempt(attempt(allowsActiveReplacement = true)),
        )
    }

    @Test
    fun staleCallbackCannotRunAgainstReplacedDecoderOrGeneration() {
        val firstDecoder = Any()
        val secondDecoder = Any()
        val port = FakePort(publishedDecoder = firstDecoder)
        val owner = AndroidDecoderLifecycleOwner(port)
        val firstAttempt = attempt(sessionGeneration = SESSION_GENERATION)
        var callbacks = 0

        assertTrue(owner.runIfActive(firstDecoder, firstAttempt) { callbacks++ })

        port.publishedDecoder = secondDecoder
        assertFalse(owner.runIfActive(firstDecoder, firstAttempt) { callbacks++ })
        assertFalse(owner.runIfActive(secondDecoder, attempt(sessionGeneration = SESSION_GENERATION + 1)) { callbacks++ })
        assertTrue(owner.runIfActive(secondDecoder, firstAttempt) { callbacks++ })

        assertEquals(2, callbacks)
    }

    @Test
    fun creationFailureReportsOnlyCurrentAttemptAndRetriesStaleCurrentSurfaceWait() {
        val port = FakePort()
        val owner = AndroidDecoderLifecycleOwner(port)
        val currentAttempt = attempt(failSession = true)
        val structural = structuralFailure()

        assertEquals(
            DecoderLifecycleCommitResult.Failed(STRUCTURAL_HEVC_TARGET_UNSUPPORTED_REASON),
            owner.handleCreationFailure(currentAttempt, DecoderInitializationException(structural)),
        )
        assertEquals(listOf(StreamCodec.HEVC to structural), port.structuralFailures)
        assertEquals(listOf(STRUCTURAL_HEVC_TARGET_UNSUPPORTED_REASON to true), port.reportedFailures)

        port.current = false
        port.canRetry = true
        assertEquals(
            DecoderLifecycleCommitResult.RetryWhenSurfaceReady,
            owner.handleCreationFailure(currentAttempt, IllegalStateException("surface disappeared")),
        )
        assertEquals(1, port.reportedFailures.size)

        port.canRetry = false
        assertEquals(
            DecoderLifecycleCommitResult.Failed(STALE_DECODER_CONFIGURATION),
            owner.handleCreationFailure(currentAttempt, IllegalStateException("stale")),
        )
        assertEquals(1, port.reportedFailures.size)
    }

    @Test
    fun structuralFallbackRequiresCurrentHevcStructuralFailure() {
        val port = FakePort()
        val owner = AndroidDecoderLifecycleOwner(port)
        val decoder = Any()
        val structural = structuralFailure()

        port.publishedDecoder = decoder
        assertTrue(owner.recordActiveStructuralFailure(decoder, attempt(codec = StreamCodec.HEVC), structural))
        assertFalse(owner.recordActiveStructuralFailure(decoder, attempt(codec = StreamCodec.H264), structural))
        assertFalse(
            owner.recordActiveStructuralFailure(
                decoder,
                attempt(codec = StreamCodec.HEVC),
                DecoderFailure(DecoderFailureKind.SESSION_RUNTIME_FAILURE, "runtime"),
            ),
        )

        port.publishedDecoder = Any()
        assertFalse(owner.recordActiveStructuralFailure(decoder, attempt(codec = StreamCodec.HEVC), structural))
    }

    @Test
    fun commitPublishesAfterScaleUpdateAndDoesNotReleaseOnSuccess() {
        val port = FakePort()
        val owner = AndroidDecoderLifecycleOwner(port)
        val decoder = Any()

        val result = owner.commitCreatedDecoder(attempt(), decoder) { publish -> publish() }

        assertEquals(DecoderLifecycleCommitResult.Configured, result)
        assertEquals(listOf(decoder), port.scaleUpdates)
        assertEquals(decoder, port.publishedDecoder)
        assertTrue(port.commitStartupCalled)
        assertTrue(port.releasedDecoders.isEmpty())
    }

    @Test
    fun commitReleasesExactlyOnceWhenPublishDoesNotCommit() {
        val port = FakePort()
        val owner = AndroidDecoderLifecycleOwner(port)
        val decoder = Any()

        val result = owner.commitCreatedDecoder(attempt(), decoder) { false }

        assertEquals(DecoderLifecycleCommitResult.Failed(STALE_DECODER_CONFIGURATION), result)
        assertEquals(listOf(decoder), port.releasedDecoders)
    }

    @Test
    fun commitReportsStartupFailureAndReleasesOnce() {
        val startupFailure = structuralFailure()
        val port = FakePort(startupResult = DecoderStartupCommitResult.Failed(startupFailure))
        val owner = AndroidDecoderLifecycleOwner(port)
        val decoder = Any()

        val result = owner.commitCreatedDecoder(attempt(), decoder) { publish -> publish() }

        assertEquals(DecoderLifecycleCommitResult.Failed(STRUCTURAL_HEVC_TARGET_UNSUPPORTED_REASON), result)
        assertEquals(listOf(StreamCodec.HEVC to startupFailure), port.structuralFailures)
        assertEquals(listOf(STRUCTURAL_HEVC_TARGET_UNSUPPORTED_REASON to false), port.reportedFailures)
        assertEquals(listOf(decoder), port.releasedDecoders)
    }

    @Test
    fun commitReleasesOnceWhenScaleUpdateFails() {
        val port = FakePort(scaleUpdateFailure = IllegalStateException("scale failed"))
        val owner = AndroidDecoderLifecycleOwner(port)
        val decoder = Any()

        val result = owner.commitCreatedDecoder(attempt(), decoder) { publish -> publish() }

        assertEquals(DecoderLifecycleCommitResult.Failed("scale failed"), result)
        assertFalse(port.commitStartupCalled)
        assertEquals(listOf(decoder), port.releasedDecoders)
    }

    @Test
    fun commitReleasesOnceWhenStartupThrows() {
        val port = FakePort(startupThrowable = IllegalStateException("startup threw"))
        val owner = AndroidDecoderLifecycleOwner(port)
        val decoder = Any()

        try {
            owner.commitCreatedDecoder(attempt(), decoder) { publish -> publish() }
            fail("Expected startup throwable")
        } catch (failure: IllegalStateException) {
            assertEquals("startup threw", failure.message)
        }

        assertEquals(listOf(decoder), port.releasedDecoders)
    }

    @Test
    fun commitDoesNotReleasePublishedDecoderWhenStartupThrowsAfterPublish() {
        val port =
            FakePort(
                startupThrowable = IllegalStateException("post publish dispatch failed"),
                publishBeforeStartupThrowable = true,
            )
        val owner = AndroidDecoderLifecycleOwner(port)
        val decoder = Any()

        try {
            owner.commitCreatedDecoder(attempt(), decoder) { publish -> publish() }
            fail("Expected startup throwable")
        } catch (failure: IllegalStateException) {
            assertEquals("post publish dispatch failed", failure.message)
        }

        assertEquals(decoder, port.publishedDecoder)
        assertTrue(port.releasedDecoders.isEmpty())
    }

    @Test
    fun boundaryOwnerStaysIndependentOfAndroidMainActivityTransportAndCodecLayers() {
        val source = repositorySource(PRODUCTION_DECODER_LIFECYCLE_OWNER)

        FORBIDDEN_OWNER_REFERENCES.forEach { reference ->
            assertFalse(
                "AndroidDecoderLifecycleOwner must not depend on `$reference`",
                source.contains(reference),
            )
        }
    }

    private fun attempt(
        sessionGeneration: Long = SESSION_GENERATION,
        codec: StreamCodec = StreamCodec.HEVC,
        failSession: Boolean = false,
        allowsActiveReplacement: Boolean = false,
        current: () -> Boolean = { true },
    ) = DecoderLifecycleAttempt(
        sessionToken = SESSION_TOKEN,
        sessionGeneration = sessionGeneration,
        surfaceToken = SURFACE_TOKEN,
        surfaceGeneration = 11L,
        configurationToken = CONFIGURATION_TOKEN,
        configurationGeneration = 13L,
        configEpoch = 17L,
        codec = codec,
        failSessionOnFailure = failSession,
        allowsActiveDecoderReplacement = allowsActiveReplacement,
        isConfigurationCurrent = current,
    )

    private fun structuralFailure() =
        DecoderFailure(
            DecoderFailureKind.STRUCTURAL_TARGET_UNSUPPORTED,
            STRUCTURAL_HEVC_TARGET_UNSUPPORTED_REASON,
        )

    private class FakePort(
        var activeDecoder: Any? = null,
        var publishedDecoder: Any? = null,
        var current: Boolean = true,
        var currentSessionGeneration: Long = SESSION_GENERATION,
        var canRetry: Boolean = true,
        private val startupResult: DecoderStartupCommitResult = DecoderStartupCommitResult.Committed,
        private val startupThrowable: Throwable? = null,
        private val publishBeforeStartupThrowable: Boolean = false,
        private val scaleUpdateFailure: RuntimeException? = null,
    ) : AndroidDecoderLifecyclePort<Any> {
        val scaleUpdates = mutableListOf<Any>()
        val releasedDecoders = mutableListOf<Any>()
        val structuralFailures = mutableListOf<Pair<StreamCodec, DecoderFailure>>()
        val reportedFailures = mutableListOf<Pair<String, Boolean>>()
        var commitStartupCalled = false

        override fun hasBlockingActiveDecoder(attempt: DecoderLifecycleAttempt): Boolean =
            !attempt.allowsActiveDecoderReplacement && activeDecoder != null

        override fun isAttemptCurrent(attempt: DecoderLifecycleAttempt): Boolean =
            isCurrent(attempt)

        override fun canRetryAttempt(attempt: DecoderLifecycleAttempt): Boolean = canRetry

        override fun isPublishedDecoderCurrent(
            decoder: Any,
            attempt: DecoderLifecycleAttempt,
        ): Boolean = isCurrent(attempt) && decoder === publishedDecoder

        private fun isCurrent(attempt: DecoderLifecycleAttempt): Boolean =
            current &&
                attempt.sessionGeneration == currentSessionGeneration &&
                attempt.isConfigurationCurrent()

        override fun updateScaleMode(decoder: Any) {
            scaleUpdateFailure?.let { throw it }
            scaleUpdates += decoder
        }

        override fun commitStartup(
            decoder: Any,
            publish: () -> Boolean,
        ): DecoderStartupCommitResult {
            commitStartupCalled = true
            if (publishBeforeStartupThrowable) {
                publish()
            }
            startupThrowable?.let { throw it }
            return if (startupResult == DecoderStartupCommitResult.Committed && !publish()) {
                DecoderStartupCommitResult.NotCommitted
            } else {
                startupResult
            }
        }

        override fun publishDecoder(
            decoder: Any,
            attempt: DecoderLifecycleAttempt,
        ): Boolean {
            publishedDecoder = decoder
            activeDecoder = decoder
            return true
        }

        override fun releaseDecoder(decoder: Any) {
            releasedDecoders += decoder
        }

        override fun recordStructuralFailure(
            codec: StreamCodec,
            failure: DecoderFailure,
            isCurrentConfiguration: () -> Boolean,
        ): Boolean {
            if (!isCurrentConfiguration()) return false
            if (codec != StreamCodec.HEVC ||
                failure.kind != DecoderFailureKind.STRUCTURAL_TARGET_UNSUPPORTED
            ) {
                return false
            }
            structuralFailures += codec to failure
            return true
        }

        override fun reportInitializationFailure(error: Exception, failSession: Boolean) {
            reportedFailures += (error.message ?: "") to failSession
        }
    }

    private fun repositorySource(relativePath: String): String {
        var current = File(requireNotNull(System.getProperty("user.dir"))).canonicalFile
        repeat(8) {
            listOf(relativePath, "baseline/AndroidClient/$relativePath")
                .map(current::resolve)
                .firstOrNull(File::isFile)
                ?.let { return it.readText() }
            current = current.parentFile?.canonicalFile ?: current
        }
        error("$relativePath not found from ${System.getProperty("user.dir")}")
    }

    private companion object {
        const val STALE_DECODER_CONFIGURATION = "stale_decoder_configuration"
        const val SESSION_GENERATION = 7L
        const val SESSION_TOKEN = "session"
        const val SURFACE_TOKEN = "surface"
        const val CONFIGURATION_TOKEN = "configuration"
        const val PRODUCTION_DECODER_LIFECYCLE_OWNER =
            "app/src/main/java/dev/telemachus/display/AndroidDecoderLifecycleOwner.kt"

        val FORBIDDEN_OWNER_REFERENCES =
            listOf(
                "import android.",
                "import androidx.",
                "MainActivity",
                "StreamTransportOwner",
                "SocketStreamTransportConnection",
                "java.net.Socket",
                "VideoDecoder",
                "MediaCodec",
                "StreamProtocolSideEffectOwner",
                "ProtocolV1Session",
            )
    }
}
