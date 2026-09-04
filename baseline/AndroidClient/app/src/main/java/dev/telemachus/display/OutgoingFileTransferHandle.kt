package dev.telemachus.display

import com.google.protobuf.ByteString

internal data class OutgoingFileTransferHandle(
    val transferId: ByteString,
    val fileName: String,
    val byteLength: Long,
)
