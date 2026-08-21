package dev.telemachus.display.protocol

import dev.vibescreen.protocol.v1.Envelope
import dev.vibescreen.protocol.v1.Capability
import dev.vibescreen.protocol.v1.FileChunkHeader
import dev.vibescreen.protocol.v1.MediaPacketHeader
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.IOException
import java.io.InputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder

class ProtocolV1FramingTest {
    @Test
    fun crossPlatformGoldenControlBytesRoundTripExactly() {
        val directory = fixtures().resolve("bin")
        directory
            .listFiles { file ->
                file.extension == "binpb" &&
                    file.name !in setOf("media_packet_header.binpb", "file_chunk_header.binpb")
            }!!
            .sortedBy(File::getName)
            .forEach { file ->
            val golden = file.readBytes()
            assertArrayEquals(file.name, golden, Envelope.parseFrom(golden).toByteArray())
        }
        val clientHello = Envelope.parseFrom(directory.resolve("client_hello.binpb").readBytes()).clientHello
        assertEquals(listOf(Capability.CAPABILITY_TOUCH), clientHello.requiredCapabilitiesList)
        assertEquals(
            90,
            Envelope.parseFrom(directory.resolve("video_config.binpb").readBytes()).videoConfig.rotationDegrees,
        )
        assertEquals(
            270,
            Envelope.parseFrom(directory.resolve("display_changed.binpb").readBytes()).displayChanged.rotationDegrees,
        )
    }

    @Test
    fun crossPlatformUpgradeAndMediaBytesAreExact() {
        val directory = fixtures().resolve("bin")
        assertArrayEquals(byteArrayOf(0x0d), directory.resolve("upgrade_offer.bin").readBytes())
        assertArrayEquals(byteArrayOf(0x0d, 0x01), directory.resolve("upgrade_acknowledgement.bin").readBytes())

        val golden = directory.resolve("media_packet.bin").readBytes()
        val decoded = ProtocolV1Framing.decodeVideo(golden)
        assertEquals(42L, decoded.header.streamId)
        assertEquals(1, decoded.header.fragmentCount)
        assertArrayEquals(golden, ProtocolV1Framing.encodeVideo(decoded.header, decoded.annexB))

        val fileChunk = directory.resolve("file_chunk.bin").readBytes()
        val decodedChunk = ProtocolV1Framing.decodeFileChunk(fileChunk)
        assertEquals(7L, decodedChunk.header.sessionEpoch)
        assertArrayEquals("hello".toByteArray(), decodedChunk.payload)
        assertArrayEquals(fileChunk, ProtocolV1Framing.encodeFileChunk(decodedChunk.header, decodedChunk.payload))
    }

    @Test
    fun splitReadsAndCoalescedFramesPreserveChannels() {
        val bytes = ByteArrayOutputStream()
        ProtocolV1Framing.write(bytes, ProtocolChannel.CONTROL, byteArrayOf(1, 2, 3))
        ProtocolV1Framing.write(bytes, ProtocolChannel.VIDEO, byteArrayOf(4, 5))
        ProtocolV1Framing.write(bytes, ProtocolChannel.AUDIO, byteArrayOf(6, 7, 8))
        ProtocolV1Framing.write(bytes, ProtocolChannel.BULK, byteArrayOf(9, 10, 11, 12))
        val input = OneByteInputStream(bytes.toByteArray())

        val control = ProtocolV1Framing.read(input)
        assertEquals(ProtocolChannel.CONTROL, control.channel)
        assertArrayEquals(byteArrayOf(1, 2, 3), control.payload)
        val video = ProtocolV1Framing.read(input)
        assertEquals(ProtocolChannel.VIDEO, video.channel)
        assertArrayEquals(byteArrayOf(4, 5), video.payload)
        val audio = ProtocolV1Framing.read(input)
        assertEquals(ProtocolChannel.AUDIO, audio.channel)
        assertArrayEquals(byteArrayOf(6, 7, 8), audio.payload)
        val bulk = ProtocolV1Framing.read(input)
        assertEquals(ProtocolChannel.BULK, bulk.channel)
        assertArrayEquals(byteArrayOf(9, 10, 11, 12), bulk.payload)
    }

    @Test
    fun rejectsUnknownChannelAndOversizedLength() {
        assertThrows(IOException::class.java) {
            ProtocolV1Framing.read(ByteArrayInputStream(byteArrayOf(9, 0, 0, 0, 0)))
        }
        val prefix =
            ByteBuffer
                .allocate(5)
                .order(ByteOrder.BIG_ENDIAN)
                .put(ProtocolChannel.CONTROL.wireValue.toByte())
                .putInt(ProtocolV1Framing.MAX_FRAME_BYTES + 1)
                .array()
        assertThrows(IOException::class.java) { ProtocolV1Framing.read(ByteArrayInputStream(prefix)) }
    }

    @Test
    fun validatesMediaLengthsAndSingleHeaderEncoding() {
        val header = MediaPacketHeader.newBuilder().setPayloadLength(3).build()
        val encoded = ProtocolV1Framing.encodeVideo(header, byteArrayOf(1, 2, 3))
        val corrupted = encoded.copyOf().also { it[it.lastIndex] = 4 }
        assertArrayEquals(byteArrayOf(1, 2, 4), ProtocolV1Framing.decodeVideo(corrupted).annexB)
        assertThrows(IllegalArgumentException::class.java) {
            ProtocolV1Framing.encodeVideo(header, byteArrayOf(1))
        }
    }

    @Test
    fun validatesFileChunkLengthsAndSingleHeaderEncoding() {
        val header = FileChunkHeader.newBuilder().setPayloadLength(3).build()
        val encoded = ProtocolV1Framing.encodeFileChunk(header, byteArrayOf(1, 2, 3))
        val corrupted = encoded.copyOf().also { it[it.lastIndex] = 4 }
        assertArrayEquals(byteArrayOf(1, 2, 4), ProtocolV1Framing.decodeFileChunk(corrupted).payload)
        assertThrows(IllegalArgumentException::class.java) {
            ProtocolV1Framing.encodeFileChunk(header, byteArrayOf(1))
        }
    }

    private fun fixtures(): File {
        val workingDirectory = requireNotNull(System.getProperty("user.dir"))
        var current = File(workingDirectory).canonicalFile
        repeat(6) {
            val candidate = current.resolve("contracts/fixtures/messages/v1")
            if (candidate.isDirectory) return candidate
            current = current.parentFile?.canonicalFile ?: current
        }
        error("Protocol v1 fixtures not found from $workingDirectory")
    }

    private class OneByteInputStream(bytes: ByteArray) : InputStream() {
        private val delegate = ByteArrayInputStream(bytes)

        override fun read(): Int = delegate.read()

        override fun read(
            target: ByteArray,
            offset: Int,
            length: Int,
        ): Int = delegate.read(target, offset, length.coerceAtMost(1))
    }
}
