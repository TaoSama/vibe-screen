package dev.telemachus.display.protocol

import com.google.protobuf.ByteString
import dev.vibescreen.protocol.v1.FileChunkHeader
import dev.vibescreen.protocol.v1.FileOffer
import dev.vibescreen.protocol.v1.ManagedPolicyStatus
import dev.vibescreen.protocol.v1.ResourceLimits
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.io.File
import java.nio.file.Files

class FileTransferSessionTest {
    @Test
    fun safeFilenameRejectsPathTraversalAndSeparators() {
        assertTrue(IncomingFileTransferManager.isSafeFileName("hello.txt"))
        assertFalse(IncomingFileTransferManager.isSafeFileName(""))
        assertFalse(IncomingFileTransferManager.isSafeFileName("."))
        assertFalse(IncomingFileTransferManager.isSafeFileName(".."))
        assertFalse(IncomingFileTransferManager.isSafeFileName("../escape.txt"))
        assertFalse(IncomingFileTransferManager.isSafeFileName("dir/file.txt"))
        assertFalse(IncomingFileTransferManager.isSafeFileName("dir\\file.txt"))
        assertFalse(IncomingFileTransferManager.isSafeFileName("bad\u0000name"))
    }

    @Test
    fun managedPolicyAndPeerLimitsResolveDenyWins() {
        val remoteStatus =
            ProtocolV1Session.ManagedPolicy.UNMANAGED.copy(
                isManaged = true,
                fileTransferAllowed = false,
                maximumFileBytes = 5,
            ).toStatus()
        val peerLimits =
            ResourceLimits
                .newBuilder()
                .setMaximumFileBytes(7)
                .setMaximumFileChunkBytes(4)
                .build()
        val policy =
            FileTransferPolicy(
                allowed = true,
                maximumFileBytes = 10,
                maximumChunkBytes = 8,
                maximumConcurrentTransfers = 1,
                maximumTotalTemporaryBytes = 20,
            )

        val managed = policy.applying(RemoteManagedPolicy(remoteStatus))
        assertFalse(managed.allowed)
        assertEquals(5L, managed.maximumFileBytes)

        val negotiated = policy.negotiated(peerLimits)
        assertTrue(negotiated.allowed)
        assertEquals(7L, negotiated.maximumFileBytes)
        assertEquals(4, negotiated.maximumChunkBytes)
    }

    @Test
    fun incomingManagerDeniesWhenApprovalCallbackReturnsFalse() {
        val manager = IncomingFileTransferManager(FileTransferPolicy(), temporaryDirectory()) { false }

        val failure = assertFileTransferFailure("user_denied") {
            manager.accept(
                offer(payload = "hello".toByteArray()),
                remotePolicy = RemoteManagedPolicy.UNMANAGED,
                negotiatedPolicy = FileTransferPolicy(),
                sessionEpoch = 7,
            )
        }
        assertEquals("File transfer denied by user", failure.message)
        assertEquals(0, manager.activeTransferCount())
    }

    @Test
    fun incomingManagerAcceptsOrderedChunksAndVerifiesCompletedDigest() {
        val payload = "hello".toByteArray()
        val directory = temporaryDirectory()
        val manager =
            IncomingFileTransferManager(
                policy = FileTransferPolicy(maximumChunkBytes = 3),
                directory = directory,
            ) { true }
        val offer = offer(payload = payload)
        val accept = manager.accept(
            offer,
            remotePolicy = RemoteManagedPolicy.UNMANAGED,
            negotiatedPolicy = FileTransferPolicy(maximumChunkBytes = 3),
            sessionEpoch = 7,
        )
        assertTrue(accept.accepted)
        assertEquals(3, accept.maximumChunkBytes)

        assertEquals(3L, manager.append(chunk(offer, offset = 0, payload = "hel".toByteArray(), final = false), 7))
        assertEquals(5L, manager.append(chunk(offer, offset = 3, payload = "lo".toByteArray(), final = true), 7))

        val completed = manager.finish(offer.transferId)
        assertEquals("hello.txt", completed.fileName)
        assertEquals(sha256(payload), completed.sha256)
        assertArrayEquals(payload, completed.stagingFile.readBytes())
        assertEquals(0, manager.activeTransferCount())
    }

    @Test
    fun incomingManagerAcceptsSingleFinalChunkForEmptyFile() {
        val directory = temporaryDirectory()
        val manager =
            IncomingFileTransferManager(
                policy = FileTransferPolicy(maximumChunkBytes = 3),
                directory = directory,
            ) { true }
        val offer = offer(payload = ByteArray(0))
        manager.accept(
            offer,
            remotePolicy = RemoteManagedPolicy.UNMANAGED,
            negotiatedPolicy = FileTransferPolicy(maximumChunkBytes = 3),
            sessionEpoch = 7,
        )

        assertEquals(0L, manager.append(chunk(offer, offset = 0, payload = ByteArray(0), final = true), 7))
        val completed = manager.finish(offer.transferId)
        assertEquals(sha256(ByteArray(0)), completed.sha256)
        assertArrayEquals(ByteArray(0), completed.stagingFile.readBytes())
    }

    @Test
    fun incomingManagerRejectsUnexpectedEmptyNonFinalChunk() {
        val manager =
            IncomingFileTransferManager(
                policy = FileTransferPolicy(maximumChunkBytes = 3),
                directory = temporaryDirectory(),
            ) { true }
        val offer = offer(payload = "hello".toByteArray())
        manager.accept(offer, RemoteManagedPolicy.UNMANAGED, FileTransferPolicy(), sessionEpoch = 7)

        assertFileTransferFailure("empty_chunk") {
            manager.append(chunk(offer, offset = 0, payload = ByteArray(0), final = false), 7)
        }
    }

    @Test
    fun incomingManagerRejectsDigestOffsetEpochAndCleansCancel() {
        val directory = temporaryDirectory()
        val manager =
            IncomingFileTransferManager(
                policy = FileTransferPolicy(maximumChunkBytes = 8),
                directory = directory,
            ) { true }
        val offer = offer(payload = "hello".toByteArray())
        manager.accept(offer, RemoteManagedPolicy.UNMANAGED, FileTransferPolicy(), sessionEpoch = 7)

        assertFileTransferFailure("unexpected_offset") {
            manager.append(chunk(offer, offset = 1, payload = "h".toByteArray(), final = false), 7)
        }
        assertFileTransferFailure("stale_session_epoch") {
            manager.append(chunk(offer, offset = 0, payload = "h".toByteArray(), final = false, headerEpoch = 6), 7)
        }

        val corrupted = chunk(offer, offset = 0, payload = "h".toByteArray(), final = false).toFrame()
        corrupted[corrupted.lastIndex] = (corrupted[corrupted.lastIndex].toInt() xor 0x01).toByte()
        assertFileTransferFailure("chunk_digest_mismatch") { FileChunk.fromFrame(corrupted) }

        manager.cancel(offer.transferId)
        assertEquals(0, manager.activeTransferCount())
        assertTrue(directory.listFiles()?.isEmpty() == true)
    }

    @Test
    fun incomingManagerRejectsChunkSizeLengthAndFinalFlagBoundaries() {
        assertFileTransferFailure("chunk_too_large") {
            acceptedIncomingManager(maximumChunkBytes = 2).let { (manager, offer) ->
                manager.append(chunk(offer, offset = 0, payload = "hel".toByteArray(), final = false), 7)
            }
        }

        assertFileTransferFailure("exceeds_declared_length") {
            acceptedIncomingManager().let { (manager, offer) ->
                manager.append(chunk(offer, offset = 0, payload = "hello!".toByteArray(), final = true), 7)
            }
        }

        assertFileTransferFailure("invalid_final_flag") {
            acceptedIncomingManager().let { (manager, offer) ->
                manager.append(chunk(offer, offset = 0, payload = "he".toByteArray(), final = true), 7)
            }
        }

        assertFileTransferFailure("invalid_final_flag") {
            acceptedIncomingManager().let { (manager, offer) ->
                manager.append(chunk(offer, offset = 0, payload = "hello".toByteArray(), final = false), 7)
            }
        }
    }

    @Test
    fun incomingManagerRejectsFinalDigestMismatchAndCleansStagingFile() {
        val directory = temporaryDirectory()
        val manager =
            IncomingFileTransferManager(
                policy = FileTransferPolicy(maximumChunkBytes = 8),
                directory = directory,
            ) { true }
        val payload = "hello".toByteArray()
        val offer = offer(payload = payload)
            .toBuilder()
            .setSha256(sha256("wrong".toByteArray()))
            .build()
        manager.accept(offer, RemoteManagedPolicy.UNMANAGED, FileTransferPolicy(), sessionEpoch = 7)
        assertEquals(5L, manager.append(chunk(offer, offset = 0, payload = payload, final = true), 7))

        assertFileTransferFailure("digest_mismatch") { manager.finish(offer.transferId) }

        assertEquals(0, manager.activeTransferCount())
        assertTrue(directory.listFiles()?.isEmpty() == true)
    }

    @Test
    fun incomingManagerFailClosedForPolicyLimitsAndUnsafeOfferBeforeApproval() {
        var approvalCalls = 0
        val manager = IncomingFileTransferManager(
            policy = FileTransferPolicy(maximumFileBytes = 4),
            directory = temporaryDirectory(),
        ) {
            approvalCalls += 1
            true
        }

        assertFileTransferFailure("invalid_file_name") {
            manager.accept(
                offer(fileName = "../escape.txt", payload = "hello".toByteArray()),
                remotePolicy = RemoteManagedPolicy.UNMANAGED,
                negotiatedPolicy = FileTransferPolicy(maximumFileBytes = 4),
                sessionEpoch = 7,
            )
        }
        assertEquals(0, approvalCalls)

        assertFileTransferFailure("file_too_large") {
            manager.accept(
                offer(payload = "hello".toByteArray()),
                remotePolicy = RemoteManagedPolicy.UNMANAGED,
                negotiatedPolicy = FileTransferPolicy(maximumFileBytes = 4),
                sessionEpoch = 7,
            )
        }
        assertEquals(0, approvalCalls)

        val negativeLengthDirectory = temporaryDirectory()
        val negativeLengthManager = IncomingFileTransferManager(
            policy = FileTransferPolicy(maximumFileBytes = 4),
            directory = negativeLengthDirectory,
        ) {
            approvalCalls += 1
            true
        }
        assertFileTransferFailure("invalid_byte_length") {
            negativeLengthManager.accept(
                offer(payload = "hi".toByteArray())
                    .toBuilder()
                    .setByteLength(-1)
                    .build(),
                remotePolicy = RemoteManagedPolicy.UNMANAGED,
                negotiatedPolicy = FileTransferPolicy(maximumFileBytes = 4),
                sessionEpoch = 7,
            )
        }
        assertEquals(0, approvalCalls)
        assertEquals(0, negativeLengthManager.activeTransferCount())
        assertTrue(negativeLengthDirectory.listFiles()?.isEmpty() == true)

        val denied =
            ProtocolV1Session.ManagedPolicy.UNMANAGED.copy(
                isManaged = true,
                fileTransferAllowed = false,
                maximumFileBytes = 10,
            ).toStatus()
        assertFileTransferFailure("policy_denied") {
            manager.accept(
                offer(payload = "hi".toByteArray()),
                remotePolicy = RemoteManagedPolicy(denied),
                negotiatedPolicy = FileTransferPolicy(),
                sessionEpoch = 7,
            )
        }
        assertEquals(0, approvalCalls)
    }

    @Test
    fun incomingManagerRejectsOfferExceedingConcurrentTransferLimit() {
        val directory = temporaryDirectory()
        val manager = IncomingFileTransferManager(
            policy = FileTransferPolicy(maximumConcurrentTransfers = 1),
            directory = directory,
        ) { true }
        val first = offer(payload = "first".toByteArray())
        val second = offer(payload = "second".toByteArray())
            .toBuilder()
            .setTransferId(ByteString.copyFrom(byteArrayOf(9, 8, 7, 6)))
            .build()
        manager.accept(first, RemoteManagedPolicy.UNMANAGED, FileTransferPolicy(maximumConcurrentTransfers = 1), sessionEpoch = 7)

        assertFileTransferFailure("concurrent_limit") {
            manager.accept(second, RemoteManagedPolicy.UNMANAGED, FileTransferPolicy(maximumConcurrentTransfers = 1), sessionEpoch = 7)
        }

        assertEquals(1, manager.activeTransferCount())
        assertEquals(1, directory.listFiles()?.size)
    }

    @Test
    fun incomingManagerAllowsConfiguredConcurrentTransfersUntilLimit() {
        val directory = temporaryDirectory()
        val policy = FileTransferPolicy(maximumConcurrentTransfers = 2)
        val manager = IncomingFileTransferManager(
            policy = policy,
            directory = directory,
        ) { true }
        val first = offer(payload = "first".toByteArray())
        val second = offer(payload = "second".toByteArray())
            .toBuilder()
            .setTransferId(ByteString.copyFrom(byteArrayOf(9, 8, 7, 6)))
            .build()
        val third = offer(payload = "third".toByteArray())
            .toBuilder()
            .setTransferId(ByteString.copyFrom(byteArrayOf(6, 7, 8, 9)))
            .build()

        manager.accept(first, RemoteManagedPolicy.UNMANAGED, policy, sessionEpoch = 7)
        manager.accept(second, RemoteManagedPolicy.UNMANAGED, policy, sessionEpoch = 7)

        assertFileTransferFailure("concurrent_limit") {
            manager.accept(third, RemoteManagedPolicy.UNMANAGED, policy, sessionEpoch = 7)
        }
        assertEquals(2, manager.activeTransferCount())
        assertEquals(2, directory.listFiles()?.size)
    }

    @Test
    fun incomingManagerRejectsOfferExceedingTemporarySpaceLimit() {
        val oversizedDirectory = temporaryDirectory()
        val oversizedManager = IncomingFileTransferManager(
            policy = FileTransferPolicy(maximumFileBytes = 10, maximumTotalTemporaryBytes = 4),
            directory = oversizedDirectory,
        ) { true }

        assertFileTransferFailure("temporary_space_limit") {
            oversizedManager.accept(
                offer(payload = "hello".toByteArray()),
                remotePolicy = RemoteManagedPolicy.UNMANAGED,
                negotiatedPolicy = FileTransferPolicy(maximumFileBytes = 10, maximumTotalTemporaryBytes = 4),
                sessionEpoch = 7,
            )
        }
        assertEquals(0, oversizedManager.activeTransferCount())
        assertTrue(oversizedDirectory.listFiles()?.isEmpty() == true)

        val cumulativeDirectory = temporaryDirectory()
        val cumulativeManager = IncomingFileTransferManager(
            policy = FileTransferPolicy(maximumConcurrentTransfers = 2, maximumFileBytes = 10, maximumTotalTemporaryBytes = 8),
            directory = cumulativeDirectory,
        ) { true }
        val first = offer(payload = "first".toByteArray())
        val second = offer(payload = "more".toByteArray())
            .toBuilder()
            .setTransferId(ByteString.copyFrom(byteArrayOf(9, 8, 7, 6)))
            .build()
        cumulativeManager.accept(
            first,
            remotePolicy = RemoteManagedPolicy.UNMANAGED,
            negotiatedPolicy = FileTransferPolicy(maximumConcurrentTransfers = 2, maximumFileBytes = 10, maximumTotalTemporaryBytes = 8),
            sessionEpoch = 7,
        )

        assertFileTransferFailure("temporary_space_limit") {
            cumulativeManager.accept(
                second,
                remotePolicy = RemoteManagedPolicy.UNMANAGED,
                negotiatedPolicy = FileTransferPolicy(maximumConcurrentTransfers = 2, maximumFileBytes = 10, maximumTotalTemporaryBytes = 8),
                sessionEpoch = 7,
            )
        }
        assertEquals(1, cumulativeManager.activeTransferCount())
        assertEquals(1, cumulativeDirectory.listFiles()?.size)
    }

    @Test
    fun incomingManagerAcceptsTemporarySpaceBoundaryEqualToLimit() {
        val exactDirectory = temporaryDirectory()
        val exactPolicy = FileTransferPolicy(maximumFileBytes = 10, maximumTotalTemporaryBytes = 5)
        val exactManager = IncomingFileTransferManager(
            policy = exactPolicy,
            directory = exactDirectory,
        ) { true }

        exactManager.accept(
            offer(payload = "hello".toByteArray()),
            remotePolicy = RemoteManagedPolicy.UNMANAGED,
            negotiatedPolicy = exactPolicy,
            sessionEpoch = 7,
        )
        assertEquals(1, exactManager.activeTransferCount())

        val cumulativeDirectory = temporaryDirectory()
        val cumulativePolicy = FileTransferPolicy(
            maximumConcurrentTransfers = 2,
            maximumFileBytes = 10,
            maximumTotalTemporaryBytes = 9,
        )
        val cumulativeManager = IncomingFileTransferManager(
            policy = cumulativePolicy,
            directory = cumulativeDirectory,
        ) { true }
        val first = offer(payload = "first".toByteArray())
        val second = offer(payload = "more".toByteArray())
            .toBuilder()
            .setTransferId(ByteString.copyFrom(byteArrayOf(9, 8, 7, 6)))
            .build()

        cumulativeManager.accept(first, RemoteManagedPolicy.UNMANAGED, cumulativePolicy, sessionEpoch = 7)
        cumulativeManager.accept(second, RemoteManagedPolicy.UNMANAGED, cumulativePolicy, sessionEpoch = 7)

        assertEquals(2, cumulativeManager.activeTransferCount())
        assertEquals(2, cumulativeDirectory.listFiles()?.size)
    }

    @Test
    fun incomingManagerAppendRejectsUnknownTransfer() {
        val directory = temporaryDirectory()
        val manager = IncomingFileTransferManager(FileTransferPolicy(), directory) { true }
        val offer = offer(payload = "hello".toByteArray())

        assertFileTransferFailure("unknown_transfer") {
            manager.append(chunk(offer, offset = 0, payload = "hello".toByteArray(), final = true), sessionEpoch = 7)
        }

        assertEquals(0, manager.activeTransferCount())
        assertTrue(directory.listFiles()?.isEmpty() == true)
    }

    @Test
    fun incomingManagerCancelUnknownTransferLeavesActiveTransferInPlace() {
        val directory = temporaryDirectory()
        val manager = IncomingFileTransferManager(FileTransferPolicy(), directory) { true }
        val offer = offer(payload = "hello".toByteArray())
        val unknownTransferId = ByteString.copyFrom(byteArrayOf(9, 8, 7, 6))
        manager.accept(offer, RemoteManagedPolicy.UNMANAGED, FileTransferPolicy(), sessionEpoch = 7)

        assertFalse(manager.cancel(unknownTransferId))

        assertTrue(manager.contains(offer.transferId))
        assertEquals(1, manager.activeTransferCount())
        assertEquals(1, directory.listFiles()?.size)
    }

    @Test
    fun incomingManagerFinishRejectsIncompleteFileOrUnknownTransfer() {
        val directory = temporaryDirectory()
        val manager = IncomingFileTransferManager(FileTransferPolicy(maximumChunkBytes = 4), directory) { true }
        val offer = offer(payload = "hello".toByteArray())

        assertFileTransferFailure("unknown_transfer") { manager.finish(offer.transferId) }

        manager.accept(offer, RemoteManagedPolicy.UNMANAGED, FileTransferPolicy(maximumChunkBytes = 4), sessionEpoch = 7)
        assertEquals(2L, manager.append(chunk(offer, offset = 0, payload = "he".toByteArray(), final = false), 7))

        assertFileTransferFailure("incomplete_file") { manager.finish(offer.transferId) }

        assertEquals(1, manager.activeTransferCount())
        assertEquals(5L, manager.append(chunk(offer, offset = 2, payload = "llo".toByteArray(), final = true), 7))
        val completed = manager.finish(offer.transferId)
        assertEquals("hello.txt", completed.fileName)
        assertArrayEquals("hello".toByteArray(), completed.stagingFile.readBytes())
    }

    @Test
    fun incomingManagerRejectsEmptyFileWhenRemoteManagedMaximumIsZeroBeforeApproval() {
        var approvalCalls = 0
        val manager = IncomingFileTransferManager(
            policy = FileTransferPolicy(),
            directory = temporaryDirectory(),
        ) {
            approvalCalls += 1
            true
        }
        val zeroMaximum =
            ProtocolV1Session.ManagedPolicy.UNMANAGED.copy(
                isManaged = true,
                fileTransferAllowed = true,
                maximumFileBytes = 0,
            ).toStatus()

        assertFileTransferFailure("policy_denied") {
            manager.accept(
                offer(payload = ByteArray(0)),
                remotePolicy = RemoteManagedPolicy(zeroMaximum),
                negotiatedPolicy = FileTransferPolicy(),
                sessionEpoch = 7,
            )
        }
        assertEquals(0, approvalCalls)
    }

    @Test
    fun outgoingTransferRejectsEmptyFileWhenRemoteManagedMaximumIsZero() {
        val file = File(temporaryDirectory(), "empty.txt")
        file.writeBytes(ByteArray(0))
        val zeroMaximum =
            ProtocolV1Session.ManagedPolicy.UNMANAGED.copy(
                isManaged = true,
                fileTransferAllowed = true,
                maximumFileBytes = 0,
            ).toStatus()

        assertFileTransferFailure("policy_denied") {
            OutgoingFileTransfer(
                file = file,
                mimeType = "text/plain",
                policy = FileTransferPolicy(),
                remotePolicy = RemoteManagedPolicy(zeroMaximum),
            )
        }
    }

    @Test
    fun outgoingTransferBuildsOfferAndBoundedChunks() {
        val file = File(temporaryDirectory(), "send.txt")
        file.writeBytes("hello".toByteArray())
        val transfer = OutgoingFileTransfer(
            file = file,
            mimeType = "text/plain",
            policy = FileTransferPolicy(maximumChunkBytes = 3),
        )
        assertEquals("send.txt", transfer.offer.fileName)
        assertEquals("text/plain", transfer.offer.mimeType)
        assertEquals(5L, transfer.offer.byteLength)
        assertEquals(sha256("hello".toByteArray()), transfer.offer.sha256)

        val first = requireNotNull(transfer.nextChunk(maximumBytes = 2, sessionEpoch = 7))
        assertEquals(0L, first.header.offset)
        assertEquals(7L, first.header.sessionEpoch)
        assertEquals(2, first.header.payloadLength)
        assertFalse(first.header.final)
        val decoded = FileChunk.fromFrame(first.toFrame())
        assertEquals(first.header, decoded.header)
        assertArrayEquals(first.payload, decoded.payload)

        val second = requireNotNull(transfer.nextChunk(maximumBytes = 8, sessionEpoch = 7))
        assertEquals(2L, second.header.offset)
        assertArrayEquals("llo".toByteArray(), second.payload)
        assertTrue(second.header.final)
        assertFalse(transfer.hasCompletedAcknowledgement())
        assertEquals(null, transfer.acknowledgeOffset(5))
        assertTrue(transfer.hasCompletedAcknowledgement())
        assertEquals(null, transfer.nextChunk(maximumBytes = 8, sessionEpoch = 7))
    }

    @Test
    fun outgoingTransferSupportsEmptyFileWithSingleFinalChunk() {
        val file = File(temporaryDirectory(), "empty.txt")
        file.writeBytes(ByteArray(0))
        val transfer = OutgoingFileTransfer(
            file = file,
            mimeType = "text/plain",
            policy = FileTransferPolicy(maximumChunkBytes = 3),
        )

        assertEquals("incomplete_file", transfer.acknowledgeOffset(0))
        assertFalse(transfer.hasCompletedAcknowledgement())
        val chunk = requireNotNull(transfer.nextChunk(maximumBytes = 2, sessionEpoch = 7))
        assertEquals(0L, chunk.header.offset)
        assertEquals(0, chunk.header.payloadLength)
        assertTrue(chunk.header.final)
        assertEquals(sha256(ByteArray(0)), chunk.header.chunkSha256)
        assertFalse(transfer.hasCompletedAcknowledgement())
        assertEquals(null, transfer.acknowledgeOffset(0))
        assertTrue(transfer.hasCompletedAcknowledgement())
        val decoded = FileChunk.fromFrame(chunk.toFrame())
        assertEquals(chunk.header, decoded.header)
        assertArrayEquals(chunk.payload, decoded.payload)
        assertEquals(null, transfer.nextChunk(maximumBytes = 2, sessionEpoch = 7))
    }

    @Test
    fun outgoingTransferRemembersAcceptedChunkLimitForProgressDrivenSending() {
        val file = File(temporaryDirectory(), "send.txt")
        file.writeBytes("hello".toByteArray())
        val transfer = OutgoingFileTransfer(
            file = file,
            mimeType = "text/plain",
            policy = FileTransferPolicy(maximumChunkBytes = 5),
        )
        transfer.applyAcceptedMaximumChunkBytes(2)

        assertEquals(2, transfer.maximumChunkBytes(defaultBytes = 5))
        val first = requireNotNull(transfer.nextChunk(maximumBytes = transfer.maximumChunkBytes(defaultBytes = 5), sessionEpoch = 7))
        assertArrayEquals("he".toByteArray(), first.payload)
    }

    @Test
    fun outgoingTransferRejectsUnexpectedProgressAndCancelBlocksFurtherChunks() {
        val file = File(temporaryDirectory(), "send.txt")
        file.writeBytes("hello".toByteArray())
        val transfer = OutgoingFileTransfer(
            file = file,
            mimeType = "text/plain",
            policy = FileTransferPolicy(maximumChunkBytes = 3),
        )

        val first = requireNotNull(transfer.nextChunk(maximumBytes = 2, sessionEpoch = 7))
        assertEquals(2L, first.header.offset + first.header.payloadLength)
        assertEquals("unexpected_progress", transfer.acknowledgeOffset(5))
        transfer.cancel()

        assertFileTransferFailure("unknown_transfer") { transfer.nextChunk(maximumBytes = 2, sessionEpoch = 7) }
    }

    @Test
    fun incomingManagerCancelAllRemovesEveryActiveStagingFile() {
        val directory = temporaryDirectory()
        val manager = IncomingFileTransferManager(
            policy = FileTransferPolicy(maximumConcurrentTransfers = 2),
            directory = directory,
        ) { true }
        val first = offer(payload = "first".toByteArray())
        val second = offer(payload = "second".toByteArray())
            .toBuilder()
            .setTransferId(ByteString.copyFrom(byteArrayOf(9, 8, 7, 6)))
            .build()
        manager.accept(first, RemoteManagedPolicy.UNMANAGED, FileTransferPolicy(maximumConcurrentTransfers = 2), sessionEpoch = 7)
        manager.accept(second, RemoteManagedPolicy.UNMANAGED, FileTransferPolicy(maximumConcurrentTransfers = 2), sessionEpoch = 7)
        assertEquals(2, manager.activeTransferCount())
        assertEquals(2, directory.listFiles()?.size)

        manager.cancelAll()

        assertEquals(0, manager.activeTransferCount())
        assertTrue(directory.listFiles()?.isEmpty() == true)
    }

    @Test
    fun bulkTransportFrameCarriesFileChunkPayload() {
        val offer = offer(payload = "hello".toByteArray())
        val framePayload = chunk(offer, offset = 0, payload = "hello".toByteArray(), final = true).toFrame()
        val output = java.io.ByteArrayOutputStream()
        ProtocolV1Framing.write(output, ProtocolChannel.BULK, framePayload)
        val decoded = ProtocolV1Framing.read(java.io.ByteArrayInputStream(output.toByteArray()))
        assertEquals(ProtocolChannel.BULK, decoded.channel)
        assertArrayEquals(framePayload, decoded.payload)
    }

    private fun temporaryDirectory(): File =
        Files.createTempDirectory("vibescreen-file-transfer-test-").toFile().also { it.deleteOnExit() }

    private fun acceptedIncomingManager(
        maximumChunkBytes: Int = 8,
    ): Pair<IncomingFileTransferManager, FileOffer> {
        val manager = IncomingFileTransferManager(
            policy = FileTransferPolicy(maximumChunkBytes = maximumChunkBytes),
            directory = temporaryDirectory(),
        ) { true }
        val offer = offer(payload = "hello".toByteArray())
        manager.accept(
            offer,
            remotePolicy = RemoteManagedPolicy.UNMANAGED,
            negotiatedPolicy = FileTransferPolicy(maximumChunkBytes = maximumChunkBytes),
            sessionEpoch = 7,
        )
        return manager to offer
    }

    private fun offer(
        fileName: String = "hello.txt",
        payload: ByteArray,
    ): FileOffer =
        FileOffer
            .newBuilder()
            .setTransferId(ByteString.copyFrom(byteArrayOf(1, 2, 3, 4)))
            .setFileName(fileName)
            .setMimeType("text/plain")
            .setByteLength(payload.size.toLong())
            .setSha256(sha256(payload))
            .build()

    private fun chunk(
        offer: FileOffer,
        offset: Long,
        payload: ByteArray,
        final: Boolean,
        headerEpoch: Long = 7,
    ): FileChunk {
        val header =
            FileChunkHeader
                .newBuilder()
                .setTransferId(offer.transferId)
                .setOffset(offset)
                .setPayloadLength(payload.size)
                .setSessionEpoch(headerEpoch)
                .setChunkSha256(sha256(payload))
                .setFinal(final)
                .build()
        return FileChunk(header, payload)
    }

    private fun assertFileTransferFailure(
        reasonCode: String,
        block: () -> Unit,
    ): FileTransferException {
        val failure = assertThrows(FileTransferException::class.java, block)
        assertEquals(reasonCode, failure.reasonCode)
        return failure
    }
}
