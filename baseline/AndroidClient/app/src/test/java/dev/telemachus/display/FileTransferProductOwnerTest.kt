package dev.telemachus.display

import com.google.protobuf.ByteString
import dev.telemachus.display.protocol.CompletedIncomingFile
import dev.telemachus.display.protocol.FileChunk
import dev.telemachus.display.protocol.FileTransferException
import dev.telemachus.display.protocol.FileTransferPolicy
import dev.telemachus.display.protocol.ProtocolV1Session
import dev.telemachus.display.protocol.RemoteManagedPolicy
import dev.telemachus.display.protocol.sha256
import dev.vibescreen.protocol.v1.FileAccept
import dev.vibescreen.protocol.v1.FileChunkHeader
import dev.vibescreen.protocol.v1.FileOffer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.io.IOException
import java.nio.file.Files

class FileTransferProductOwnerTest {
    @Test
    fun `stale file offer decisions are cleared on disconnect`() {
        val gate = FakePendingOfferGate()
        val store = FakeIncomingTransferStore(stagingDirectory())
        val owner = owner(gate = gate, store = store)
        val session = Any()
        val offer = offer(id = 1, payload = "hello".toByteArray())
        var callbackCount = 0
        owner.onFileOffer = { callbackCount += 1 }
        owner.activateSession()

        assertNull(owner.receiveFileOffer(session, connectionGeneration = 7, offer = offer))
        assertEquals(1, callbackCount)
        assertNotNull(owner.claimFileOfferDecision(offer))

        assertNull(owner.receiveFileOffer(session, connectionGeneration = 7, offer = offer))
        owner.clear()

        assertNull(owner.claimFileOfferDecision(offer))
        assertEquals(0, owner.activeIncomingTransferCount())
        assertTrue(gate.clearCount >= 2)
    }

    @Test
    fun `disconnect cleanup cancels incoming outgoing and pending product state`() {
        val gate = FakePendingOfferGate()
        val store = FakeIncomingTransferStore(stagingDirectory())
        val owner = owner(gate = gate, store = store)
        owner.activateSession()
        val session = Any()
        val offer = offer(id = 2, payload = "incoming".toByteArray())
        owner.onFileOffer = {}

        assertNull(owner.receiveFileOffer(session, connectionGeneration = 9, offer = offer))
        assertTrue(
            owner.decideFileOffer(
                offer = offer,
                acceptedByUser = true,
                negotiatedPolicy = FileTransferPolicy(),
                sessionEpoch = 3,
            ).accepted,
        )
        assertEquals(1, owner.activeIncomingTransferCount())

        val outgoingFile = File(stagingDirectory(), "outgoing.txt").also { it.writeText("outgoing") }
        val prepared = owner.prepareOutgoingFile(outgoingFile, "text/plain", FileTransferPolicy())
            as FileTransferProductOwner.PrepareOutgoingResult.Prepared
        assertNotNull(owner.startPreparedOutgoing(prepared.transfer, canTransferFiles = true))
        assertEquals(1, owner.activeOutgoingTransferCount())

        owner.clear()

        assertEquals(0, owner.activeIncomingTransferCount())
        assertEquals(0, owner.activeOutgoingTransferCount())
        assertEquals(1, store.cancelAllCount)
        assertNull(owner.claimFileOfferDecision(offer))

        val late = owner.receiveIncomingChunk(chunk(offer, payload = "incoming".toByteArray(), final = true), true, 3)
        assertTrue(late is FileTransferProductOwner.IncomingChunkResult.Rejected)
        assertEquals("policy_denied", (late as FileTransferProductOwner.IncomingChunkResult.Rejected).reasonCode)
    }

    @Test
    fun `incoming write failures fail closed and cancel the transfer`() {
        val store = FakeIncomingTransferStore(stagingDirectory())
        val owner = owner(store = store)
        val offer = offer(id = 3, payload = "denied".toByteArray())
        owner.activateSession()
        assertTrue(
            owner.decideFileOffer(
                offer = offer,
                acceptedByUser = true,
                negotiatedPolicy = FileTransferPolicy(),
                sessionEpoch = 4,
            ).accepted,
        )

        store.appendFailure = IOException("disk denied")
        val result = owner.receiveIncomingChunk(chunk(offer, payload = "denied".toByteArray(), final = true), true, 4)

        assertTrue(result is FileTransferProductOwner.IncomingChunkResult.Rejected)
        result as FileTransferProductOwner.IncomingChunkResult.Rejected
        assertEquals("io_failure", result.reasonCode)
        assertEquals(offer.transferId, result.transferId)
        assertTrue(result.failure is IOException)
        assertEquals(listOf(offer.transferId), store.cancelledTransfers)
        assertEquals(0, owner.activeIncomingTransferCount())
    }

    @Test
    fun `duplicate transfer ids fail closed before product callbacks or storage writes multiply`() {
        val gate = FakePendingOfferGate(maximumPendingOffers = 1)
        val store = FakeIncomingTransferStore(stagingDirectory())
        val owner = owner(gate = gate, store = store)
        val session = Any()
        val offer = offer(id = 4, payload = "duplicate".toByteArray())
        var callbackCount = 0
        owner.onFileOffer = { callbackCount += 1 }
        owner.activateSession()

        assertNull(owner.receiveFileOffer(session, connectionGeneration = 11, offer = offer))
        val duplicatePending = owner.receiveFileOffer(session, connectionGeneration = 11, offer = offer)

        assertFalse(requireNotNull(duplicatePending).accepted)
        assertEquals("file_offer_pending_limit", duplicatePending.rejectionReason)
        assertEquals(1, callbackCount)

        assertTrue(
            owner.decideFileOffer(
                offer = offer,
                acceptedByUser = true,
                negotiatedPolicy = FileTransferPolicy(),
                sessionEpoch = 5,
            ).accepted,
        )
        val duplicateAccepted = owner.decideFileOffer(
            offer = offer,
            acceptedByUser = true,
            negotiatedPolicy = FileTransferPolicy(),
            sessionEpoch = 5,
        )

        assertFalse(duplicateAccepted.accepted)
        assertEquals("duplicate_transfer", duplicateAccepted.rejectionReason)
        assertEquals(1, owner.activeIncomingTransferCount())
    }

    @Test
    fun `managed policy denial clears pending offers and rejects new file work`() {
        val gate = FakePendingOfferGate()
        val store = FakeIncomingTransferStore(stagingDirectory())
        val owner = owner(gate = gate, store = store)
        val session = Any()
        val offer = offer(id = 5, payload = "managed".toByteArray())
        var callbackCount = 0
        owner.onFileOffer = { callbackCount += 1 }
        owner.activateSession()

        assertNull(owner.receiveFileOffer(session, connectionGeneration = 13, offer = offer))
        owner.applyManagedPolicy(
            ProtocolV1Session.ManagedPolicy.UNMANAGED.copy(
                isManaged = true,
                fileTransferAllowed = false,
                maximumFileBytes = 1024,
            ).toStatus(),
        )

        assertNull(owner.claimFileOfferDecision(offer))
        assertEquals(1, store.cancelAllCount)
        val newOffer = offer(id = 6, payload = "managed-denied".toByteArray())
        val rejectedBeforeCallback = owner.receiveFileOffer(session, connectionGeneration = 13, offer = newOffer)
        assertFalse(requireNotNull(rejectedBeforeCallback).accepted)
        assertEquals("policy_denied", rejectedBeforeCallback.rejectionReason)
        assertEquals(1, callbackCount)

        val denied = owner.decideFileOffer(
            offer = offer,
            acceptedByUser = true,
            negotiatedPolicy = FileTransferPolicy(),
            sessionEpoch = 6,
        )
        assertFalse(denied.accepted)
        assertEquals("policy_denied", denied.rejectionReason)
    }

    @Test
    fun `managed zero byte limit clears pending offers before user callback`() {
        val gate = FakePendingOfferGate()
        val store = FakeIncomingTransferStore(stagingDirectory())
        val owner = owner(gate = gate, store = store)
        val session = Any()
        val offer = offer(id = 7, payload = ByteArray(0))
        var callbackCount = 0
        owner.onFileOffer = { callbackCount += 1 }
        owner.activateSession()

        assertNull(owner.receiveFileOffer(session, connectionGeneration = 17, offer = offer))
        owner.applyManagedPolicy(
            ProtocolV1Session.ManagedPolicy.UNMANAGED.copy(
                isManaged = true,
                fileTransferAllowed = true,
                maximumFileBytes = 0,
            ).toStatus(),
        )

        assertNull(owner.claimFileOfferDecision(offer))
        assertEquals(1, store.cancelAllCount)
        val rejected = owner.receiveFileOffer(
            session,
            connectionGeneration = 17,
            offer = offer(id = 8, payload = ByteArray(0)),
        )
        assertFalse(requireNotNull(rejected).accepted)
        assertEquals("policy_denied", rejected.rejectionReason)
        assertEquals(1, callbackCount)
    }

    @Test
    fun `prepared outgoing transfers are cancelled when owner clears before start`() {
        val outgoing = FakeOutgoingTransferStore(id = 9, payload = "pending".toByteArray())
        val owner = owner(outgoing = outgoing)
        owner.activateSession()

        val prepared = owner.prepareOutgoingFile(
            File(stagingDirectory(), "pending.txt").also { it.writeText("pending") },
            "text/plain",
            FileTransferPolicy(),
        ) as FileTransferProductOwner.PrepareOutgoingResult.Prepared

        assertEquals(0, outgoing.cancelCount)

        owner.clear()

        assertEquals(1, outgoing.cancelCount)
        assertEquals(0, owner.activeOutgoingTransferCount())
        owner.cancelPreparedOutgoing(prepared.transfer)
        assertEquals(1, outgoing.cancelCount)
        assertNull(owner.startPreparedOutgoing(prepared.transfer, canTransferFiles = true))
        assertEquals(1, outgoing.cancelCount)
    }

    @Test
    fun `managed policy denial cancels prepared outgoing before start`() {
        val outgoing = FakeOutgoingTransferStore(id = 10, payload = "managed-pending".toByteArray())
        val owner = owner(outgoing = outgoing)
        owner.activateSession()

        val prepared = owner.prepareOutgoingFile(
            File(stagingDirectory(), "managed-pending.txt").also { it.writeText("managed-pending") },
            "text/plain",
            FileTransferPolicy(),
        ) as FileTransferProductOwner.PrepareOutgoingResult.Prepared

        owner.applyManagedPolicy(
            ProtocolV1Session.ManagedPolicy.UNMANAGED.copy(
                isManaged = true,
                fileTransferAllowed = false,
                maximumFileBytes = 1024,
            ).toStatus(),
        )

        assertEquals(1, outgoing.cancelCount)
        owner.cancelPreparedOutgoing(prepared.transfer)
        assertEquals(1, outgoing.cancelCount)
        assertNull(owner.startPreparedOutgoing(prepared.transfer, canTransferFiles = true))
        assertEquals(1, outgoing.cancelCount)
    }

    @Test
    fun `cancel prepared outgoing releases unstarted transfer exactly once`() {
        val outgoing = FakeOutgoingTransferStore(id = 11, payload = "cancel-prepared".toByteArray())
        val owner = owner(outgoing = outgoing)
        owner.activateSession()

        val prepared = owner.prepareOutgoingFile(
            File(stagingDirectory(), "cancel-prepared.txt").also { it.writeText("cancel-prepared") },
            "text/plain",
            FileTransferPolicy(),
        ) as FileTransferProductOwner.PrepareOutgoingResult.Prepared

        owner.cancelPreparedOutgoing(prepared.transfer)
        owner.cancelPreparedOutgoing(prepared.transfer)

        assertEquals(1, outgoing.cancelCount)
        assertNull(owner.startPreparedOutgoing(prepared.transfer, canTransferFiles = true))
        assertEquals(1, outgoing.cancelCount)
    }

    @Test
    fun `restarting an active outgoing transfer does not cancel its store`() {
        val outgoing = FakeOutgoingTransferStore(id = 12, payload = "active".toByteArray())
        val owner = owner(outgoing = outgoing)
        owner.activateSession()

        val prepared = owner.prepareOutgoingFile(
            File(stagingDirectory(), "active.txt").also { it.writeText("active") },
            "text/plain",
            FileTransferPolicy(),
        ) as FileTransferProductOwner.PrepareOutgoingResult.Prepared

        assertNotNull(owner.startPreparedOutgoing(prepared.transfer, canTransferFiles = true))
        assertNull(owner.startPreparedOutgoing(prepared.transfer, canTransferFiles = true))
        owner.cancelPreparedOutgoing(prepared.transfer)

        assertEquals(0, outgoing.cancelCount)
        assertEquals(1, owner.activeOutgoingTransferCount())

        owner.clear()

        assertEquals(1, outgoing.cancelCount)
    }

    private fun owner(
        gate: FakePendingOfferGate = FakePendingOfferGate(),
        store: FakeIncomingTransferStore = FakeIncomingTransferStore(stagingDirectory()),
        outgoing: FileTransferProductOwner.OutgoingTransferStore? = null,
    ): FileTransferProductOwner {
        if (outgoing == null) {
            return FileTransferProductOwner(
                stagingDirectory = ::stagingDirectory,
                pendingOfferGate = gate,
                incomingManagerFactory = FileTransferProductOwner.IncomingManagerFactory { _, _, _ -> store },
            )
        }
        return FileTransferProductOwner(
            stagingDirectory = ::stagingDirectory,
            pendingOfferGate = gate,
            incomingManagerFactory = FileTransferProductOwner.IncomingManagerFactory { _, _, _ -> store },
            outgoingTransferFactory = FileTransferProductOwner.OutgoingTransferFactory { _, _, _, _ ->
                outgoing
            },
        )
    }

    private class FakePendingOfferGate(
        private val maximumPendingOffers: Int = 16,
    ) : FileTransferProductOwner.PendingOfferGate {
        private val offers = LinkedHashMap<ByteString, FileTransferProductOwner.PendingOfferOwner>()
        var clearCount = 0
            private set

        override fun trackFileOffer(
            transferId: ByteString,
            ownerToken: Any,
            connectionGeneration: Long,
        ): Boolean {
            if (offers.containsKey(transferId) || offers.size >= maximumPendingOffers) return false
            offers[transferId] = FileTransferProductOwner.PendingOfferOwner(ownerToken, connectionGeneration)
            return true
        }

        override fun claimFileOffer(transferId: ByteString): FileTransferProductOwner.PendingOfferOwner? =
            offers.remove(transferId)

        override fun releaseFileOffer(transferId: ByteString) {
            offers.remove(transferId)
        }

        override fun clearFileOffers() {
            clearCount += 1
            offers.clear()
        }
    }

    private class FakeIncomingTransferStore(
        private val directory: File,
    ) : FileTransferProductOwner.IncomingTransferStore {
        private val activeOffers = LinkedHashMap<ByteString, FileOffer>()
        val cancelledTransfers = mutableListOf<ByteString>()
        var cancelAllCount = 0
            private set
        var appendFailure: IOException? = null

        override fun accept(
            offer: FileOffer,
            remotePolicy: RemoteManagedPolicy,
            negotiatedPolicy: FileTransferPolicy,
            sessionEpoch: Long,
        ): FileAccept {
            val effective = negotiatedPolicy.applying(remotePolicy)
            if (!effective.allowed) throw FileTransferException("policy_denied", "File transfer denied by policy")
            if (activeOffers.containsKey(offer.transferId)) {
                throw FileTransferException("duplicate_transfer", "Duplicate file transfer")
            }
            activeOffers[offer.transferId] = offer
            return FileAccept
                .newBuilder()
                .setTransferId(offer.transferId)
                .setAccepted(true)
                .setMaximumChunkBytes(effective.maximumChunkBytes)
                .build()
        }

        override fun append(chunk: FileChunk, sessionEpoch: Long): Long {
            appendFailure?.let { throw it }
            if (!activeOffers.containsKey(chunk.header.transferId)) {
                throw FileTransferException("unknown_transfer", "Unknown file transfer")
            }
            return chunk.header.offset + chunk.payload.size
        }

        override fun finish(transferId: ByteString): CompletedIncomingFile {
            val offer = activeOffers.remove(transferId)
                ?: throw FileTransferException("unknown_transfer", "Unknown file transfer")
            val file = File(directory, offer.fileName).also { it.writeBytes(ByteArray(0)) }
            return CompletedIncomingFile(transferId, offer.fileName, offer.mimeType, file, offer.sha256)
        }

        override fun cancel(transferId: ByteString) {
            activeOffers.remove(transferId)
            cancelledTransfers += transferId
        }

        override fun cancelAll() {
            cancelAllCount += 1
            activeOffers.clear()
        }

        override fun activeTransferCount(): Int = activeOffers.size
    }

    private class FakeOutgoingTransferStore(
        id: Int,
        payload: ByteArray,
    ) : FileTransferProductOwner.OutgoingTransferStore {
        override val offer: FileOffer = offer(id = id, payload = payload)
        var cancelCount = 0
            private set

        override fun cancel() {
            cancelCount += 1
        }

        override fun applyAcceptedMaximumChunkBytes(maximumBytes: Int) = Unit

        override fun maximumChunkBytes(defaultBytes: Int): Int = defaultBytes

        override fun nextChunk(maximumBytes: Int, sessionEpoch: Long): FileChunk? = null

        override fun acknowledgeOffset(receivedBytes: Long): String? = null

        override fun hasCompletedAcknowledgement(): Boolean = true
    }

    private companion object {
        fun stagingDirectory(): File =
            Files.createTempDirectory("vibescreen-file-owner-test-").toFile().also { it.deleteOnExit() }

        fun offer(
            id: Int,
            payload: ByteArray,
            fileName: String = "file-$id.txt",
        ): FileOffer =
            FileOffer
                .newBuilder()
                .setTransferId(ByteString.copyFrom(ByteArray(16) { (id + it).toByte() }))
                .setFileName(fileName)
                .setMimeType("text/plain")
                .setByteLength(payload.size.toLong())
                .setSha256(sha256(payload))
                .build()

        fun chunk(
            offer: FileOffer,
            payload: ByteArray,
            final: Boolean,
            offset: Long = 0,
            sessionEpoch: Long = 7,
        ): FileChunk {
            val header =
                FileChunkHeader
                    .newBuilder()
                    .setTransferId(offer.transferId)
                    .setOffset(offset)
                    .setPayloadLength(payload.size)
                    .setSessionEpoch(sessionEpoch)
                    .setChunkSha256(sha256(payload))
                    .setFinal(final)
                    .build()
            return FileChunk(header, payload)
        }
    }
}
