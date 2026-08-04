package dev.telemachus.display.protocol

import java.io.IOException
import java.io.InputStream
import java.io.OutputStream

internal object ProtocolUpgrade {
    const val OFFER = 0x0d
    const val ACK_VERSION = 0x01

    sealed class Result {
        data object V1 : Result()

        data class Legacy(val firstByte: Int?) : Result()
    }

    fun writeOffer(output: OutputStream) {
        output.write(OFFER)
        output.flush()
    }

    /** A timeout is represented by [firstByte] == null so socket policy stays outside this pure adapter. */
    fun classify(
        firstByte: Int?,
        input: InputStream,
    ): Result =
        when (firstByte) {
            null -> Result.Legacy(null)
            OFFER -> {
                val version = input.read()
                if (version != ACK_VERSION) throw IOException("Invalid Protocol v1 upgrade acknowledgement")
                Result.V1
            }
            else -> Result.Legacy(firstByte)
        }
}
