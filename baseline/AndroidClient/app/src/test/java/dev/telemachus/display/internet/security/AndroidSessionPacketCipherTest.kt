package dev.telemachus.display.internet.security

import dev.telemachus.display.internet.PeerRole
import dev.telemachus.display.internet.SessionChannel
import dev.telemachus.display.internet.InternetMediaRecordContract
import java.nio.ByteBuffer
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Test

class AndroidSessionPacketCipherTest {
    private val pairingScope = pairingSecurityScope("cipher-device", "cipher-pairing")
    private val securityStore =
        CipherSecurityStore(
            DurableSecurityState(
                sessionEpochHighWatermarks = mapOf(pairingScope to 7),
                identityEpochHighWatermark = 1,
                authorizedIdentityEpoch = 1,
            ),
        )
    private val securityLifecycle = SecurityLifecycle(securityStore)

    @Test
    fun authenticatesBothDirectionsAndSeparatesChannels() {
        val host = cipher(PeerRole.HOST)
        val device = cipher(PeerRole.DEVICE)

        val control = host.seal(SessionChannel.CONTROL, byteArrayOf(1, 2))
        val media = device.seal(SessionChannel.MEDIA, byteArrayOf(3, 4))

        assertArrayEquals(byteArrayOf(1, 2), device.open(SessionChannel.CONTROL, control))
        assertArrayEquals(byteArrayOf(3, 4), host.open(SessionChannel.MEDIA, media))
        assertNull(device.open(SessionChannel.MEDIA, control))
    }

    @Test
    fun rejectsReplayTamperAndOtherSession() {
        val host = cipher(PeerRole.HOST)
        val device = cipher(PeerRole.DEVICE)
        val otherSession = cipher(PeerRole.DEVICE, sessionId = "other")
        val record = host.seal(SessionChannel.CONTROL, byteArrayOf(8))

        assertArrayEquals(byteArrayOf(8), device.open(SessionChannel.CONTROL, record))
        assertNull(device.open(SessionChannel.CONTROL, record))
        assertNull(otherSession.open(SessionChannel.CONTROL, record))
        val tampered = record.copyOf().apply { this[lastIndex] = (this[lastIndex].toInt() xor 1).toByte() }
        assertNull(cipher(PeerRole.DEVICE).open(SessionChannel.CONTROL, tampered))
    }

    @Test
    fun rotationDestroysOldEpochAndAcceptsNewRecordsForEveryChannelClass() {
        val host = cipher(PeerRole.HOST)
        val device = cipher(PeerRole.DEVICE)
        val oldRecord = host.seal(SessionChannel.MEDIA, byteArrayOf(5))
        val oldAudio = host.seal(SessionChannel.AUDIO, byteArrayOf(7))
        val oldBulk = device.seal(SessionChannel.BULK, byteArrayOf(8))
        val updateNonce = ByteArray(16) { it.toByte() }

        host.rotateTrafficKeys(updateNonce)
        device.rotateTrafficKeys(updateNonce)
        val newRecord = host.seal(SessionChannel.MEDIA, byteArrayOf(6))
        val newAudio = host.seal(SessionChannel.AUDIO, byteArrayOf(9))
        val newBulk = device.seal(SessionChannel.BULK, byteArrayOf(10))

        assertNull(device.open(SessionChannel.MEDIA, oldRecord))
        assertNull(device.open(SessionChannel.AUDIO, oldAudio))
        assertNull(host.open(SessionChannel.BULK, oldBulk))
        assertArrayEquals(byteArrayOf(6), device.open(SessionChannel.MEDIA, newRecord))
        assertArrayEquals(byteArrayOf(9), device.open(SessionChannel.AUDIO, newAudio))
        assertArrayEquals(byteArrayOf(10), host.open(SessionChannel.BULK, newBulk))
    }

    @Test
    fun failedSealConsumesDurableNonceBeforeNextRecord() {
        val invalidKeys = keysWithInvalidHostAudioKey()
        val invalidCipher = cipher(PeerRole.HOST, initialKeys = invalidKeys)

        assertThrows(IllegalArgumentException::class.java) {
            invalidCipher.seal(SessionChannel.AUDIO, byteArrayOf(1))
        }

        val nextCipher = cipher(PeerRole.HOST)
        val nextRecord = nextCipher.seal(SessionChannel.AUDIO, byteArrayOf(2))
        assertArrayEquals(
            ByteBuffer.allocate(12).putInt(3).putLong(2).array(),
            nextRecord.copyOfRange(39, 51),
        )
        invalidCipher.close()
        nextCipher.close()
    }

    @Test
    fun controlIsStrictlyMonotonicWhileMediaAllowsBoundedReordering() {
        val host = cipher(PeerRole.HOST)
        val device = cipher(PeerRole.DEVICE)
        val firstControl = host.seal(SessionChannel.CONTROL, byteArrayOf(1))
        val secondControl = host.seal(SessionChannel.CONTROL, byteArrayOf(2))
        val firstMedia = host.seal(SessionChannel.MEDIA, byteArrayOf(3))
        val secondMedia = host.seal(SessionChannel.MEDIA, byteArrayOf(4))

        assertArrayEquals(byteArrayOf(2), device.open(SessionChannel.CONTROL, secondControl))
        assertNull(device.open(SessionChannel.CONTROL, firstControl))
        assertArrayEquals(byteArrayOf(4), device.open(SessionChannel.MEDIA, secondMedia))
        assertArrayEquals(byteArrayOf(3), device.open(SessionChannel.MEDIA, firstMedia))
    }

    @Test
    fun advancedChannelsUseIndependentKeysSequencesAndReplayWindows() {
        val host = cipher(PeerRole.HOST)
        val device = cipher(PeerRole.DEVICE)
        val otherSession = cipher(PeerRole.DEVICE, sessionId = "phase5-other-session")
        val audioOne = host.seal(SessionChannel.AUDIO, byteArrayOf(1))
        val audioTwo = host.seal(SessionChannel.AUDIO, byteArrayOf(2))
        val bulkOne = host.seal(SessionChannel.BULK, byteArrayOf(3))
        val bulkTwo = host.seal(SessionChannel.BULK, byteArrayOf(4))

        assertNull(device.open(SessionChannel.BULK, audioOne))
        assertArrayEquals(byteArrayOf(2), device.open(SessionChannel.AUDIO, audioTwo))
        assertArrayEquals(byteArrayOf(1), device.open(SessionChannel.AUDIO, audioOne))
        assertArrayEquals(byteArrayOf(4), device.open(SessionChannel.BULK, bulkTwo))
        assertNull(device.open(SessionChannel.BULK, bulkOne))
        assertNull(device.open(SessionChannel.AUDIO, audioTwo))
        assertNull(otherSession.open(SessionChannel.BULK, bulkTwo))
    }

    @Test
    fun declaredSessionChannelRecognizesAudioAndBulkRecords() {
        val host = cipher(PeerRole.HOST)
        val device = cipher(PeerRole.DEVICE)
        val audio = host.seal(SessionChannel.AUDIO, byteArrayOf(1))
        val bulk = device.seal(SessionChannel.BULK, byteArrayOf(2))

        assertEquals(SessionChannel.AUDIO, AndroidSessionPacketCipher.declaredSessionChannel(audio))
        assertEquals(SessionChannel.BULK, AndroidSessionPacketCipher.declaredSessionChannel(bulk))
    }

    @Test
    fun maximumPlaintextMediaRecordSealsWithinFourMiBAndroidBoundary() {
        val host = cipher(PeerRole.HOST)
        val plaintext = ByteArray(InternetMediaRecordContract.MAXIMUM_PLAINTEXT_RECORD_BYTES)

        val record = host.seal(SessionChannel.MEDIA, plaintext)

        assertEquals(InternetMediaRecordContract.MAXIMUM_ENCRYPTED_RECORD_BYTES, record.size)
    }

    @Test
    fun staleDurableSessionEpochRejectsSealAndOpenBeforeCryptography() {
        val host = cipher(PeerRole.HOST)
        val device = cipher(PeerRole.DEVICE)
        val record = host.seal(SessionChannel.CONTROL, byteArrayOf(9))

        assertThrows(IllegalArgumentException::class.java) {
            securityLifecycle.reserveSessionEpoch(pairingScope, 1, Long.MAX_VALUE)
        }
        securityLifecycle.reserveSessionEpoch(pairingScope, 1, 8)

        assertThrows(IllegalStateException::class.java) { host.seal(SessionChannel.CONTROL, byteArrayOf(10)) }
        assertThrows(IllegalStateException::class.java) { device.open(SessionChannel.CONTROL, record) }
    }

    private fun cipher(
        role: PeerRole,
        sessionId: String = "session-1",
        initialKeys: SessionTrafficKeys = keys(),
    ) =
        AndroidSessionPacketCipher(
            sessionId = sessionId,
            sessionEpoch = 7,
            localRole = role,
            initialKeys = initialKeys,
            sealWithActiveEpoch = { epoch, channel, sender, keyEpoch, operation ->
                securityLifecycle.withReservedSessionNonce(
                    pairingScope,
                    1,
                    epoch,
                    channel,
                    sender,
                    keyEpoch,
                    operation,
                )
            },
            openWithActiveEpoch = { epoch, operation ->
                securityLifecycle.withActiveSessionEpoch(pairingScope, 1, epoch, operation)
            },
            rotateKeys = { current, updateNonce ->
                TrafficKeyDerivation.rotate(current, current.keyEpoch + 1, updateNonce)
            },
        )

    private fun keys() =
        TrafficKeyDerivation.initial(
            sharedSecret = ByteArray(32) { 1 },
            bootstrapSecret = ByteArray(32) { 2 },
            context = ByteArray(32) { 3 },
        )

    private fun keysWithInvalidHostAudioKey(): SessionTrafficKeys {
        val source = keys()
        return SessionTrafficKeys(
            keyId = source.keyId,
            keyEpoch = source.keyEpoch,
            hostControl = source.hostControl.copyOf(),
            deviceControl = source.deviceControl.copyOf(),
            hostMedia = source.hostMedia.copyOf(),
            deviceMedia = source.deviceMedia.copyOf(),
            hostAudio = source.hostAudio.copyOf(31),
            deviceAudio = source.deviceAudio.copyOf(),
            hostBulk = source.hostBulk.copyOf(),
            deviceBulk = source.deviceBulk.copyOf(),
        ).also { source.close() }
    }
}

private class CipherSecurityStore(
    initialState: DurableSecurityState,
) : SecurityStateStore {
    private var state = initialState

    override fun load(): DurableSecurityState = state

    override fun persist(state: DurableSecurityState) {
        this.state = state
    }
}
