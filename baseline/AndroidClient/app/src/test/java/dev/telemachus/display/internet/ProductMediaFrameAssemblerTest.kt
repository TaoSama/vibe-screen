package dev.telemachus.display.internet

import dev.telemachus.display.internet.security.AndroidSessionPacketCipher
import dev.telemachus.display.internet.security.DurableSecurityState
import dev.telemachus.display.internet.security.SecurityLifecycle
import dev.telemachus.display.internet.security.SecurityStateStore
import dev.telemachus.display.internet.security.TrafficKeyDerivation
import dev.telemachus.display.internet.security.pairingSecurityScope
import dev.vibescreen.protocol.v1.Codec
import dev.vibescreen.protocol.v1.MediaPacketHeader
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

    @Test
    fun encryptedAnnexBKeyframeRecordSurvivesProtocolDecodeAndAssembly() {
        val assembler = configuredAssembler()
        val payload = hevcAnnexBKeyframePayload()

        mediaCipherPair().use { ciphers ->
            val encrypted = ciphers.host.seal(
                SessionChannel.MEDIA,
                mediaRecord(frameId = 60, payload = payload),
            )
            val plaintext = requireNotNull(ciphers.device.open(SessionChannel.MEDIA, encrypted))
            val frame = assertFrame(assembler.offer(codec.decodeMediaFragment(plaintext)))

            assertEquals(configuration.streamId, frame.streamId)
            assertEquals(7, frame.sessionEpoch)
            assertEquals(configuration.configEpoch, frame.configEpoch)
            assertEquals(60, frame.frameId)
            assertEquals(ProductVideoCodec.HEVC, frame.codec)
            assertTrue(frame.keyframe)
            assertAnnexBKeyframePayload(frame.payload)
            assertArrayEquals(payload, frame.payload)
        }
    }

    @Test
    fun encryptedFragmentedAnnexBKeyframeReassemblesAfterOutOfOrderMediaRecords() {
        val assembler = configuredAssembler()
        val payload = hevcAnnexBKeyframePayload(InternetMediaRecordContract.MAXIMUM_FRAGMENT_PAYLOAD_BYTES + 257)
        val chunks = fragmentPayloads(payload)
        assertEquals(2, chunks.size)

        mediaCipherPair().use { ciphers ->
            val encrypted =
                chunks.mapIndexed { index, chunk ->
                    ciphers.host.seal(
                        SessionChannel.MEDIA,
                        mediaRecord(
                            frameId = 61,
                            fragmentIndex = index,
                            fragmentCount = chunks.size,
                            payload = chunk,
                        ),
                    )
                }

            val second = requireNotNull(ciphers.device.open(SessionChannel.MEDIA, encrypted[1]))
            assertPending(assembler.offer(codec.decodeMediaFragment(second)))
            val first = requireNotNull(ciphers.device.open(SessionChannel.MEDIA, encrypted[0]))
            val frame = assertFrame(assembler.offer(codec.decodeMediaFragment(first)))

            assertEquals(61, frame.frameId)
            assertAnnexBKeyframePayload(frame.payload)
            assertArrayEquals(payload, frame.payload)
        }
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

    private fun fragmentPayloads(payload: ByteArray): List<ByteArray> {
        val sizes = fragmentSizes(payload.size)
        var offset = 0
        return sizes.map { size ->
            payload.copyOfRange(offset, offset + size).also { offset += size }
        }
    }

    private fun mediaRecord(
        frameId: Long,
        fragmentIndex: Int = 0,
        fragmentCount: Int = 1,
        payload: ByteArray,
    ): ByteArray {
        val header =
            MediaPacketHeader
                .newBuilder()
                .setStreamId(configuration.streamId)
                .setSessionEpoch(7)
                .setConfigEpoch(configuration.configEpoch)
                .setFrameId(frameId)
                .setFragmentIndex(fragmentIndex)
                .setFragmentCount(fragmentCount)
                .setCaptureTimestampNs(frameId * 100)
                .setKeyframe(true)
                .setCodec(Codec.CODEC_HEVC)
                .setPayloadLength(payload.size)
                .build()
        return ProtobufProtocolV1ProductCodec.encodeMediaFragment(header, payload)
    }

    private fun mediaCipherPair(): MediaCipherPair {
        val pairingScope = pairingSecurityScope("media-contract-device", "media-contract-pairing")
        val lifecycle =
            SecurityLifecycle(
                MediaContractSecurityStore(
                    DurableSecurityState(
                        sessionEpochHighWatermarks = mapOf(pairingScope to 7),
                        identityEpochHighWatermark = 1,
                        authorizedIdentityEpoch = 1,
                    ),
                ),
            )
        return MediaCipherPair(
            host = mediaCipher(PeerRole.HOST, lifecycle, pairingScope),
            device = mediaCipher(PeerRole.DEVICE, lifecycle, pairingScope),
        )
    }

    private fun mediaCipher(
        role: PeerRole,
        lifecycle: SecurityLifecycle,
        pairingScope: String,
    ) = AndroidSessionPacketCipher(
        sessionId = "session-1",
        sessionEpoch = 7,
        localRole = role,
        initialKeys = trafficKeys(),
        sealWithActiveEpoch = { epoch, channel, sender, keyEpoch, operation ->
            lifecycle.withReservedSessionNonce(pairingScope, 1, epoch, channel, sender, keyEpoch, operation)
        },
        openWithActiveEpoch = { epoch, operation ->
            lifecycle.withActiveSessionEpoch(pairingScope, 1, epoch, operation)
        },
        rotateKeys = { current, updateNonce ->
            TrafficKeyDerivation.rotate(current, current.keyEpoch + 1, updateNonce)
        },
    )

    private fun trafficKeys() =
        TrafficKeyDerivation.initial(
            sharedSecret = ByteArray(32) { 1 },
            bootstrapSecret = ByteArray(32) { 2 },
            context = ByteArray(32) { 3 },
        )

    private fun hevcAnnexBKeyframePayload(minimumBytes: Int = 0): ByteArray {
        val prefix = nal(
            0x00, 0x00, 0x00, 0x01, 0x40, 0x01, 0x0c, 0x01, 0xff, 0xff, 0x01, 0x60, 0x00, 0x00, 0x03, 0x00,
            0x90, 0x00, 0x00, 0x03, 0x00, 0x00, 0x03, 0x00, 0x3c, 0x98, 0x09,
            0x00, 0x00, 0x00, 0x01, 0x42, 0x01, 0x01, 0x01, 0x60, 0x00, 0x00, 0x03, 0x00, 0x90, 0x00,
            0x00, 0x03, 0x00, 0x00, 0x03, 0x00, 0x3c, 0xa0, 0x02, 0x80, 0x80, 0x2d, 0x16, 0x59, 0x59,
            0xa4, 0x93, 0x2b, 0xc0, 0x40,
            0x00, 0x00, 0x00, 0x01, 0x44, 0x01, 0xc0, 0xf1, 0x83, 0x10,
            0x00, 0x00, 0x00, 0x01, 0x26, 0x01, 0xaf, 0x09, 0x40,
        )
        if (minimumBytes <= prefix.size) return prefix
        return prefix + ByteArray(minimumBytes - prefix.size) { index -> (index * 31 + 17).toByte() }
    }

    private fun assertAnnexBKeyframePayload(payload: ByteArray) {
        assertTrue(payload.startsWith(annexBStartCode))
        assertTrue(countStartCodes(payload) >= 4)
    }

    private fun ByteArray.startsWith(prefix: ByteArray): Boolean =
        size >= prefix.size && prefix.indices.all { this[it] == prefix[it] }

    private fun countStartCodes(payload: ByteArray): Int =
        (0..payload.size - annexBStartCode.size).count { offset ->
            annexBStartCode.indices.all { payload[offset + it] == annexBStartCode[it] }
        }

    private fun nal(vararg values: Int): ByteArray = values.map { it.toByte() }.toByteArray()

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
        private val annexBStartCode = byteArrayOf(0, 0, 0, 1)
        private val codec = ProtobufProtocolV1ProductCodec("device-1", "Android", setOf(ProductVideoCodec.HEVC)) { 1 }
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

private data class MediaCipherPair(
    val host: AndroidSessionPacketCipher,
    val device: AndroidSessionPacketCipher,
) : AutoCloseable {
    override fun close() {
        host.close()
        device.close()
    }
}

private class MediaContractSecurityStore(
    initialState: DurableSecurityState,
) : SecurityStateStore {
    private var state = initialState

    override fun load(): DurableSecurityState = state

    override fun persist(state: DurableSecurityState) {
        this.state = state
    }
}
