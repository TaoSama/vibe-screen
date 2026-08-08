package dev.telemachus.display.internet

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ProductMediaFrameAssemblerTest {
    @Test
    fun reassemblesOutOfOrderFragments() {
        val assembler = configuredAssembler()

        assertPending(assembler.offer(fragment(frameId = 1, fragmentIndex = 2, fragmentCount = 3, payload = bytes("c"))))
        assertPending(assembler.offer(fragment(frameId = 1, fragmentIndex = 0, fragmentCount = 3, payload = bytes("a"))))
        val result = assembler.offer(fragment(frameId = 1, fragmentIndex = 1, fragmentCount = 3, payload = bytes("b")))

        val frame = assertFrame(result)
        assertArrayEquals(bytes("abc"), frame.payload)
        assertEquals(1, frame.frameId)
    }

    @Test
    fun duplicateFragmentRejectsWholeFrameAndRequiresKeyframe() {
        val assembler = configuredAssembler()
        val first = fragment(frameId = 10, fragmentIndex = 0, fragmentCount = 2, payload = bytes("a"))

        assertPending(assembler.offer(first))
        assertRecovery(
            assembler.offer(first),
            ProductMediaFrameAssembler.REASON_DUPLICATE_FRAGMENT,
        )
        assertPending(
            assembler.offer(fragment(frameId = 10, fragmentIndex = 1, fragmentCount = 2, payload = bytes("b"))),
        )
        assertArrayEquals(
            bytes("recovery"),
            assertFrame(assembler.offer(fragment(frameId = 11, payload = bytes("recovery")))).payload,
        )
    }

    @Test
    fun missingFragmentFollowedByNewDeltaDropsBothAndRequiresKeyframe() {
        val assembler = configuredAssembler()

        assertPending(
            assembler.offer(fragment(frameId = 20, fragmentIndex = 0, fragmentCount = 2, payload = bytes("old"))),
        )
        assertRecovery(
            assembler.offer(fragment(frameId = 21, keyframe = false, payload = bytes("delta"))),
            ProductMediaFrameAssembler.REASON_MISSING_FRAGMENT,
        )
        assertPending(
            assembler.offer(fragment(frameId = 20, fragmentIndex = 1, fragmentCount = 2, payload = bytes("late"))),
        )
        assertArrayEquals(
            bytes("key"),
            assertFrame(assembler.offer(fragment(frameId = 22, payload = bytes("key")))).payload,
        )
    }

    @Test
    fun newerKeyframeReplacesIncompleteFrameAndStillAcceptsOutOfOrderFragments() {
        val assembler = configuredAssembler()

        assertPending(
            assembler.offer(fragment(frameId = 30, fragmentIndex = 0, fragmentCount = 2, payload = bytes("old"))),
        )
        assertPending(
            assembler.offer(fragment(frameId = 31, fragmentIndex = 1, fragmentCount = 2, payload = bytes("b"))),
        )
        val frame =
            assertFrame(
                assembler.offer(fragment(frameId = 31, fragmentIndex = 0, fragmentCount = 2, payload = bytes("a"))),
            )

        assertArrayEquals(bytes("ab"), frame.payload)
    }

    @Test
    fun conflictingMetadataForSameFrameFailsClosed() {
        val assembler = configuredAssembler()

        assertPending(
            assembler.offer(
                fragment(
                    frameId = 40,
                    fragmentIndex = 0,
                    fragmentCount = 2,
                    payload = bytes("a"),
                    captureTimestampNs = 100,
                ),
            ),
        )
        assertRecovery(
            assembler.offer(
                fragment(
                    frameId = 40,
                    fragmentIndex = 1,
                    fragmentCount = 2,
                    payload = bytes("b"),
                    captureTimestampNs = 101,
                ),
            ),
            ProductMediaFrameAssembler.REASON_FRAGMENT_MISMATCH,
        )
    }

    @Test
    fun staleSessionFragmentDoesNotDiscardPendingFrame() {
        val assembler = configuredAssembler()

        assertPending(
            assembler.offer(fragment(frameId = 45, fragmentIndex = 0, fragmentCount = 2, payload = bytes("a"))),
        )
        assertRecovery(
            assembler.offer(
                fragment(
                    frameId = 45,
                    fragmentIndex = 1,
                    fragmentCount = 2,
                    payload = bytes("b"),
                    sessionEpoch = 8,
                ),
            ),
            ProductMediaFrameAssembler.REASON_SCOPE_MISMATCH,
        )
        assertArrayEquals(
            bytes("ab"),
            assertFrame(
                assembler.offer(fragment(frameId = 45, fragmentIndex = 1, fragmentCount = 2, payload = bytes("b"))),
            ).payload,
        )
    }

    @Test
    fun retiredConfigurationFragmentDoesNotDiscardNewConfigurationFrame() {
        val assembler = configuredAssembler()

        assertPending(
            assembler.offer(fragment(frameId = 46, fragmentIndex = 0, fragmentCount = 2, payload = bytes("new-"))),
        )
        assertPending(
            assembler.offer(
                fragment(
                    frameId = 46,
                    fragmentIndex = 1,
                    fragmentCount = 2,
                    payload = bytes("old"),
                    configEpoch = configuration.configEpoch - 1,
                ),
            ),
        )

        assertArrayEquals(
            bytes("new-frame"),
            assertFrame(
                assembler.offer(
                    fragment(frameId = 46, fragmentIndex = 1, fragmentCount = 2, payload = bytes("frame")),
                ),
            ).payload,
        )
    }

    @Test
    fun incompleteFrameExpiresAtTheMonotonicDeadlineAndRecoversOnTheNextKeyframe() {
        val clock = AssemblerFakeClock(100)
        val assembler = configuredAssembler(clock, assemblyDeadlineMillis = 50)

        assertPending(
            assembler.offer(fragment(frameId = 47, fragmentIndex = 0, fragmentCount = 2, payload = bytes("old"))),
        )
        clock.now = 149
        assertPending(assembler.expire())
        clock.now = 150
        assertRecovery(assembler.expire(), ProductMediaFrameAssembler.REASON_ASSEMBLY_TIMEOUT)
        assertPending(assembler.expire())
        assertPending(
            assembler.offer(fragment(frameId = 47, fragmentIndex = 1, fragmentCount = 2, payload = bytes("late"))),
        )

        assertArrayEquals(
            bytes("fresh"),
            assertFrame(assembler.offer(fragment(frameId = 48, payload = bytes("fresh")))).payload,
        )
    }

    @Test
    fun finalFragmentBeforeDeadlineCompletesButAtDeadlineTheNextKeyframeReplacesExpiredState() {
        val beforeDeadlineClock = AssemblerFakeClock(1_000)
        val beforeDeadline = configuredAssembler(beforeDeadlineClock, assemblyDeadlineMillis = 25)
        assertPending(
            beforeDeadline.offer(fragment(frameId = 49, fragmentIndex = 0, fragmentCount = 2, payload = bytes("a"))),
        )
        beforeDeadlineClock.now = 1_024
        assertArrayEquals(
            bytes("ab"),
            assertFrame(
                beforeDeadline.offer(
                    fragment(frameId = 49, fragmentIndex = 1, fragmentCount = 2, payload = bytes("b")),
                ),
            ).payload,
        )

        val atDeadlineClock = AssemblerFakeClock(2_000)
        val atDeadline = configuredAssembler(atDeadlineClock, assemblyDeadlineMillis = 25)
        assertPending(
            atDeadline.offer(fragment(frameId = 50, fragmentIndex = 0, fragmentCount = 2, payload = bytes("stale"))),
        )
        atDeadlineClock.now = 2_025
        assertArrayEquals(
            bytes("next-key"),
            assertFrame(atDeadline.offer(fragment(frameId = 51, payload = bytes("next-key")))).payload,
        )
    }

    @Test
    fun reservedMaximumFrameIdCannotPoisonTheConfigurationHighWatermark() {
        val assembler = configuredAssembler()

        assertPending(
            assembler.offer(fragment(frameId = 52, fragmentIndex = 0, fragmentCount = 2, payload = bytes("a"))),
        )
        assertRecovery(
            assembler.offer(fragment(frameId = Long.MAX_VALUE, payload = bytes("poison"))),
            ProductMediaFrameAssembler.REASON_INVALID_FRAGMENT,
        )
        assertArrayEquals(
            bytes("ab"),
            assertFrame(
                assembler.offer(fragment(frameId = 52, fragmentIndex = 1, fragmentCount = 2, payload = bytes("b"))),
            ).payload,
        )
        assertArrayEquals(
            bytes("next"),
            assertFrame(assembler.offer(fragment(frameId = 53, payload = bytes("next"), keyframe = false))).payload,
        )
    }

    @Test
    fun acceptsExactlySixteenMiBRecoversAfterExpiryAndRejectsTheFirstByteBeyondIt() {
        val acceptedClock = AssemblerFakeClock(0)
        val accepted = configuredAssembler(acceptedClock)
        val exactSizes = fragmentSizes(InternetMediaRecordContract.MAXIMUM_FRAME_BYTES)
        var acceptedResult: ProductMediaAssemblyResult = ProductMediaAssemblyResult.Pending
        exactSizes.forEachIndexed { index, size ->
            acceptedResult =
                accepted.offer(
                    fragment(
                        frameId = 50,
                        fragmentIndex = index,
                        fragmentCount = exactSizes.size,
                        payload = ByteArray(size) { index.toByte() },
                    ),
                )
        }
        assertEquals(InternetMediaRecordContract.MAXIMUM_FRAME_BYTES, assertFrame(acceptedResult).payload.size)
        assertPending(
            accepted.offer(
                fragment(
                    frameId = 51,
                    fragmentIndex = 0,
                    fragmentCount = exactSizes.size,
                    payload = ByteArray(exactSizes.first()),
                ),
            ),
        )
        acceptedClock.now = ProductMediaFrameAssembler.DEFAULT_ASSEMBLY_DEADLINE_MS
        assertRecovery(accepted.expire(), ProductMediaFrameAssembler.REASON_ASSEMBLY_TIMEOUT)
        assertArrayEquals(
            bytes("recovered"),
            assertFrame(accepted.offer(fragment(frameId = 52, payload = bytes("recovered")))).payload,
        )

        val rejected = configuredAssembler()
        val oversizedSizes = fragmentSizes(InternetMediaRecordContract.MAXIMUM_FRAME_BYTES + 1)
        var rejectedResult: ProductMediaAssemblyResult = ProductMediaAssemblyResult.Pending
        oversizedSizes.forEachIndexed { index, size ->
            rejectedResult =
                rejected.offer(
                    fragment(
                        frameId = 53,
                        fragmentIndex = index,
                        fragmentCount = oversizedSizes.size,
                        payload = ByteArray(size),
                    ),
                )
        }
        assertRecovery(rejectedResult, ProductMediaFrameAssembler.REASON_FRAME_TOO_LARGE)
    }

    private fun configuredAssembler(
        clock: AssemblerFakeClock = AssemblerFakeClock(0),
        assemblyDeadlineMillis: Long = ProductMediaFrameAssembler.DEFAULT_ASSEMBLY_DEADLINE_MS,
    ): ProductMediaFrameAssembler =
        ProductMediaFrameAssembler(clock, assemblyDeadlineMillis).also {
            it.startConfiguration(configuration, 7)
        }

    private fun fragmentSizes(totalBytes: Int): List<Int> {
        val result = mutableListOf<Int>()
        var remaining = totalBytes
        while (remaining > 0) {
            val size = minOf(remaining, InternetMediaRecordContract.MAXIMUM_FRAGMENT_PAYLOAD_BYTES)
            result += size
            remaining -= size
        }
        return result
    }

    private fun fragment(
        frameId: Long,
        fragmentIndex: Int = 0,
        fragmentCount: Int = 1,
        payload: ByteArray,
        keyframe: Boolean = true,
        captureTimestampNs: Long = frameId * 100,
        sessionEpoch: Long = 7,
        configEpoch: Long = configuration.configEpoch,
    ) = ProductMediaFragment(
        streamId = configuration.streamId,
        sessionEpoch = sessionEpoch,
        configEpoch = configEpoch,
        frameId = frameId,
        fragmentIndex = fragmentIndex,
        fragmentCount = fragmentCount,
        captureTimestampNs = captureTimestampNs,
        keyframe = keyframe,
        codec = configuration.codec,
        payload = payload,
    )

    private fun assertPending(result: ProductMediaAssemblyResult) {
        assertTrue(result is ProductMediaAssemblyResult.Pending)
    }

    private fun assertFrame(result: ProductMediaAssemblyResult): ProductVideoFrame {
        assertTrue(result is ProductMediaAssemblyResult.FrameReady)
        return (result as ProductMediaAssemblyResult.FrameReady).frame
    }

    private fun assertRecovery(
        result: ProductMediaAssemblyResult,
        reason: String,
    ) {
        assertTrue(result is ProductMediaAssemblyResult.KeyframeRequired)
        assertEquals(reason, (result as ProductMediaAssemblyResult.KeyframeRequired).reason)
    }

    private fun bytes(value: String): ByteArray = value.toByteArray(Charsets.UTF_8)

    companion object {
        private val configuration =
            ProductVideoConfiguration(
                configEpoch = 3,
                codec = ProductVideoCodec.HEVC,
                width = 1920,
                height = 1080,
                framesPerSecond = 60,
                bitrateKbps = 12_000,
                streamId = 5,
            )
    }
}

private class AssemblerFakeClock(var now: Long) : MonotonicClock {
    override fun nowMillis(): Long = now
}
