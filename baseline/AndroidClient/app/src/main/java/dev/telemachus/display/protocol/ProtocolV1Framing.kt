package dev.telemachus.display.protocol

import com.google.protobuf.CodedInputStream
import com.google.protobuf.CodedOutputStream
import dev.vibescreen.protocol.v1.MediaPacketHeader
import java.io.EOFException
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder

internal enum class ProtocolChannel(val wireValue: Int) {
    CONTROL(1),
    VIDEO(2),
    ;

    companion object {
        fun fromWire(value: Int): ProtocolChannel =
            entries.firstOrNull { it.wireValue == value }
                ?: throw IOException("Unknown Protocol v1 channel: $value")
    }
}

internal data class ProtocolFrame(
    val channel: ProtocolChannel,
    val payload: ByteArray,
)

/** TCP framing shared by USB/LAN. Physical multiplexing never erases logical channel identity. */
internal object ProtocolV1Framing {
    const val MAX_FRAME_BYTES = 16 * 1024 * 1024
    private const val PREFIX_BYTES = 5

    fun write(
        output: OutputStream,
        channel: ProtocolChannel,
        payload: ByteArray,
    ) {
        require(payload.size <= MAX_FRAME_BYTES) { "Protocol frame exceeds $MAX_FRAME_BYTES bytes" }
        val prefix =
            ByteBuffer
                .allocate(PREFIX_BYTES)
                .order(ByteOrder.BIG_ENDIAN)
                .put(channel.wireValue.toByte())
                .putInt(payload.size)
                .array()
        output.write(prefix)
        output.write(payload)
        output.flush()
    }

    fun read(input: InputStream): ProtocolFrame = read(input, input.read())

    fun read(
        input: InputStream,
        firstChannel: Int,
    ): ProtocolFrame {
        val channel = firstChannel
        if (channel < 0) throw EOFException("Protocol stream ended before channel")
        val sizeBytes = input.readExactly(Int.SIZE_BYTES)
        val size = ByteBuffer.wrap(sizeBytes).order(ByteOrder.BIG_ENDIAN).int
        if (size !in 0..MAX_FRAME_BYTES) throw IOException("Invalid Protocol v1 frame length: $size")
        return ProtocolFrame(ProtocolChannel.fromWire(channel), input.readExactly(size))
    }

    fun encodeVideo(
        header: MediaPacketHeader,
        annexB: ByteArray,
    ): ByteArray {
        require(header.payloadLength == annexB.size) { "Media payload_length does not match payload" }
        val headerBytes = header.toByteArray()
        val prefixSize = CodedOutputStream.computeUInt32SizeNoTag(headerBytes.size)
        return ByteArray(prefixSize + headerBytes.size + annexB.size).also { output ->
            val coded = CodedOutputStream.newInstance(output)
            coded.writeUInt32NoTag(headerBytes.size)
            coded.writeRawBytes(headerBytes)
            coded.writeRawBytes(annexB)
            coded.flush()
        }
    }

    fun decodeVideo(payload: ByteArray): VideoPayload {
        val coded = CodedInputStream.newInstance(payload)
        val headerLength = coded.readUInt32()
        if (headerLength <= 0 || headerLength > coded.bytesUntilLimit) {
            throw IOException("Invalid media header length: $headerLength")
        }
        val header = MediaPacketHeader.parseFrom(coded.readRawBytes(headerLength))
        val annexB = coded.readRawBytes(coded.bytesUntilLimit)
        if (header.payloadLength != annexB.size) throw IOException("Media payload_length mismatch")
        return VideoPayload(header, annexB)
    }

    data class VideoPayload(
        val header: MediaPacketHeader,
        val annexB: ByteArray,
    )

    private fun InputStream.readExactly(size: Int): ByteArray {
        val result = ByteArray(size)
        var offset = 0
        while (offset < size) {
            val count = read(result, offset, size - offset)
            if (count < 0) throw EOFException("Protocol stream ended with ${size - offset} bytes missing")
            if (count == 0) continue
            offset += count
        }
        return result
    }
}
