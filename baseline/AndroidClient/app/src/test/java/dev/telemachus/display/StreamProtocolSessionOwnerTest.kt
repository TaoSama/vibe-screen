package dev.telemachus.display

import com.google.protobuf.ByteString
import dev.telemachus.display.protocol.ProtocolV1Session
import dev.vibescreen.protocol.v1.Codec
import dev.vibescreen.protocol.v1.TransportKind
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

class StreamProtocolSessionOwnerTest {
    @Test
    fun `activate stores session and binds side effect gate to current generation`() {
        val owner = StreamProtocolSessionOwner()
        val session = session()
        val generation = owner.beginSession()

        owner.activate(session)
        owner.markConnected()

        assertSame(session, owner.currentSession)
        assertEquals(generation, owner.connectionGeneration)
        assertTrue(owner.isCurrent(session, generation))
    }

    @Test
    fun `deactivate clears session and side effect gate`() {
        val owner = StreamProtocolSessionOwner()
        val session = session()
        owner.beginSession()
        owner.activate(session)

        owner.deactivate()

        assertNull(owner.currentSession)
        assertFalse(owner.isCurrent(session, owner.connectionGeneration))
    }

    @Test
    fun `clear terminates session ownership`() {
        val owner = StreamProtocolSessionOwner()
        val session = session()
        owner.beginSession()
        owner.activate(session)

        owner.clear()

        assertNull(owner.currentSession)
        assertFalse(owner.isCurrent(session, owner.connectionGeneration))
    }

    @Test
    fun `stale generation is rejected after new session begins`() {
        val owner = StreamProtocolSessionOwner()
        val firstSession = session()
        val firstGeneration = owner.beginSession()
        owner.activate(firstSession)
        owner.markConnected()
        assertTrue(owner.isCurrent(firstSession, firstGeneration))

        val secondGeneration = owner.beginSession()
        val secondSession = session()
        owner.activate(secondSession)
        owner.markConnected()

        assertFalse(owner.isCurrent(firstSession, firstGeneration))
        assertFalse(owner.ownsAttempt(firstGeneration))
        assertTrue(owner.isCurrent(secondSession, secondGeneration))
        assertTrue(owner.ownsAttempt(secondGeneration))
    }

    @Test
    fun `side effect gates require current connected session owner`() {
        val owner = StreamProtocolSessionOwner()
        val session = session()
        owner.beginSession()
        owner.activate(session)
        owner.markConnected()

        val transferId = ByteString.copyFromUtf8("transfer")
        assertTrue(owner.trackFileOffer(transferId, session, owner.connectionGeneration))

        val claimed = owner.claimFileOffer(transferId)
        assertNotNull(claimed)
        assertSame(session, claimed!!.session)
        assertEquals(owner.connectionGeneration, claimed.connectionGeneration)
    }

    @Test
    fun `side effect gates fail closed after disconnect`() {
        val owner = StreamProtocolSessionOwner()
        val session = session()
        owner.beginSession()
        owner.activate(session)
        owner.markConnected()

        val transferId = ByteString.copyFromUtf8("transfer")
        assertTrue(owner.trackFileOffer(transferId, session, owner.connectionGeneration))

        owner.markDisconnected()
        assertNull(owner.claimFileOffer(transferId))
    }

    @Test
    fun `retry transition is admitted only when stop was not requested`() {
        val owner = StreamProtocolSessionOwner()
        owner.beginSession()
        owner.markConnected()
        owner.markReady()

        owner.requestStop()
        assertFalse(owner.isConnected && !owner.stopRequested)

        owner.allowResumeAfterFailure()
        assertTrue(owner.isConnected && !owner.stopRequested)
    }

    @Test
    fun `clearing side effect admission retains session for outbound drain`() {
        val owner = StreamProtocolSessionOwner()
        val session = session()
        owner.beginSession()
        owner.activate(session)
        owner.markConnected()
        val transferId = ByteString.copyFromUtf8("transfer")
        assertTrue(owner.trackFileOffer(transferId, session, owner.connectionGeneration))

        owner.markTerminationClaimed(SessionFailure.userRequested())
        owner.clearSideEffectAdmission()

        assertSame(session, owner.currentSession)
        assertTrue(owner.retainsSession(session, owner.connectionGeneration))
        assertNull(owner.claimFileOffer(transferId))
        assertFalse(owner.isCurrent(session, owner.connectionGeneration))
    }

    @Test
    fun `cleanup resets session reference and side effect admission`() {
        val owner = StreamProtocolSessionOwner()
        val session = session()
        owner.beginSession()
        owner.activate(session)
        owner.markConnected()

        val transferId = ByteString.copyFromUtf8("transfer")
        assertTrue(owner.trackFileOffer(transferId, session, owner.connectionGeneration))

        owner.clear()

        assertNull(owner.currentSession)
        assertNull(owner.claimFileOffer(transferId))
    }

    @Test
    fun `connection epoch is owned by session owner not stream client`() {
        val owner = StreamProtocolSessionOwner()
        val epoch = owner.beginSession()

        assertEquals(epoch, owner.connectionEpoch)
        assertTrue(owner.acceptsEpoch(epoch))
        assertTrue(owner.ownsCurrentEpoch())
    }

    @Test
    fun `session owner does not import android ui transport socket decoder or side effect layers`() {
        val source = source(PRODUCTION_PROTOCOL_SESSION_OWNER)

        FORBIDDEN_REFERENCES.forEach { reference ->
            assertFalse("StreamProtocolSessionOwner must not depend on `$reference`", source.contains(reference))
        }
    }

    private fun session(): ProtocolV1Session =
        ProtocolV1Session(
            deviceId = "android-test",
            deviceName = "Test Device",
            transport = TransportKind.TRANSPORT_KIND_USB,
            codecs = listOf(Codec.CODEC_H264),
            advertiseController = false,
            advertisePeripheralInputFramework = false,
        )

    private fun source(relativePath: String): String {
        var current = java.io.File(requireNotNull(System.getProperty("user.dir"))).canonicalFile
        repeat(8) {
            listOf(relativePath, "baseline/AndroidClient/$relativePath")
                .map(current::resolve)
                .firstOrNull(java.io.File::isFile)
                ?.let { return it.readText() }
            current = current.parentFile?.canonicalFile ?: current
        }
        error("$relativePath not found from " + System.getProperty("user.dir"))
    }

    private companion object {
        const val PRODUCTION_PROTOCOL_SESSION_OWNER =
            "app/src/main/java/dev/telemachus/display/StreamProtocolSessionOwner.kt"

        val FORBIDDEN_REFERENCES =
            listOf(
                "import android.",
                "import androidx.",
                "MainActivity",
                "StreamTransportOwner",
                "SocketStreamTransportConnection",
                "java.net.Socket",
                "VideoDecoder",
                "MediaCodec",
                "FileTransfer",
                "WakeHostPacketSender",
                "WakeHostDecision",
                "DataInputStream",
                "DataOutputStream",
            )
    }
}
