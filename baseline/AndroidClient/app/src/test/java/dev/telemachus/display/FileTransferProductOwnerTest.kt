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
import dev.vibescreen.protocol.v1.FileTransferCancel
import dev.vibescreen.protocol.v1.FileTransferComplete
import dev.vibescreen.protocol.v1.FileTransferProgress
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
        assertTrue(
            owner.startPreparedOutgoing(prepared.transfer, canTransferFiles = true)
                is FileTransferProductOwner.StartOutgoingResult.Started,
        )
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
    fun `incoming finish failures fail closed and cancel the transfer`() {
        val store = FakeIncomingTransferStore(stagingDirectory())
        val owner = owner(store = store)
        val offer = offer(id = 33, payload = "incomplete".toByteArray())
        owner.activateSession()
        assertTrue(
            owner.decideFileOffer(
                offer = offer,
                acceptedByUser = true,
                negotiatedPolicy = FileTransferPolicy(),
                sessionEpoch = 4,
            ).accepted,
        )

        val finishFailure = FileTransferException("incomplete_file", "Missing transfer chunk")
        store.finishFailure = finishFailure
        val result = owner.receiveIncomingChunk(chunk(offer, payload = "incomplete".toByteArray(), final = true), true, 4)

        assertTrue(result is FileTransferProductOwner.IncomingChunkResult.Rejected)
        result as FileTransferProductOwner.IncomingChunkResult.Rejected
        assertEquals("incomplete_file", result.reasonCode)
        assertEquals(offer.transferId, result.transferId)
        assertEquals(finishFailure, result.failure)
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
        val results = mutableListOf<Pair<Boolean, String>>()
        owner.onFileTransferResult = { accepted, reason -> results += accepted to reason }
        owner.activateSession()

        val prepared = owner.prepareOutgoingFile(
            File(stagingDirectory(), "pending.txt").also { it.writeText("pending") },
            "text/plain",
            FileTransferPolicy(),
        ) as FileTransferProductOwner.PrepareOutgoingResult.Prepared

        assertEquals(0, outgoing.cancelCount)

        owner.clear()

        assertEquals(1, outgoing.cancelCount)
        assertEquals(listOf(false to "connection_cleanup"), results)
        assertEquals(0, owner.activeOutgoingTransferCount())
        owner.cancelPreparedOutgoing(prepared.transfer)
        assertEquals(1, outgoing.cancelCount)
        assertEquals(
            FileTransferProductOwner.StartOutgoingResult.Stale(null),
            owner.startPreparedOutgoing(prepared.transfer, canTransferFiles = true),
        )
        assertEquals(1, outgoing.cancelCount)
    }

    @Test
    fun `clear notifies connection cleanup for active outgoing transfers by default`() {
        val outgoing = FakeOutgoingTransferStore(id = 90, payload = "active-clear".toByteArray())
        val owner = owner(outgoing = outgoing)
        val results = mutableListOf<Pair<Boolean, String>>()
        owner.onFileTransferResult = { accepted, reason -> results += accepted to reason }
        owner.activateSession()

        val prepared = owner.prepareOutgoingFile(
            File(stagingDirectory(), "active-clear.txt").also { it.writeText("active-clear") },
            "text/plain",
            FileTransferPolicy(),
        ) as FileTransferProductOwner.PrepareOutgoingResult.Prepared
        assertTrue(owner.startPreparedOutgoing(prepared.transfer, canTransferFiles = true) is FileTransferProductOwner.StartOutgoingResult.Started)

        owner.clear()

        assertEquals(1, outgoing.cancelCount)
        assertEquals(listOf(false to "connection_cleanup"), results)
    }

    @Test
    fun `activate session notifies session deactivated for previous active outgoing transfers`() {
        val outgoing = FakeOutgoingTransferStore(id = 91, payload = "active-activate".toByteArray())
        val owner = owner(outgoing = outgoing)
        val results = mutableListOf<Pair<Boolean, String>>()
        owner.onFileTransferResult = { accepted, reason -> results += accepted to reason }
        owner.activateSession()

        val prepared = owner.prepareOutgoingFile(
            File(stagingDirectory(), "active-activate.txt").also { it.writeText("active-activate") },
            "text/plain",
            FileTransferPolicy(),
        ) as FileTransferProductOwner.PrepareOutgoingResult.Prepared
        assertTrue(owner.startPreparedOutgoing(prepared.transfer, canTransferFiles = true) is FileTransferProductOwner.StartOutgoingResult.Started)

        owner.activateSession()

        assertEquals(1, outgoing.cancelCount)
        assertEquals(listOf(false to "session_deactivated"), results)
    }

    @Test
    fun `activate session notifies session deactivated for previous prepared outgoing transfers`() {
        val outgoing = FakeOutgoingTransferStore(id = 95, payload = "prepared-activate".toByteArray())
        val owner = owner(outgoing = outgoing)
        val results = mutableListOf<Pair<Boolean, String>>()
        owner.onFileTransferResult = { accepted, reason -> results += accepted to reason }
        owner.activateSession()

        val prepared = owner.prepareOutgoingFile(
            File(stagingDirectory(), "prepared-activate.txt").also { it.writeText("prepared-activate") },
            "text/plain",
            FileTransferPolicy(),
        ) as FileTransferProductOwner.PrepareOutgoingResult.Prepared

        owner.activateSession()

        assertEquals(1, outgoing.cancelCount)
        assertEquals(listOf(false to "session_deactivated"), results)
        assertEquals(
            FileTransferProductOwner.StartOutgoingResult.Stale(null),
            owner.startPreparedOutgoing(prepared.transfer, canTransferFiles = true),
        )
    }

    @Test
    fun `managed policy denial cancels prepared outgoing before start`() {
        val outgoing = FakeOutgoingTransferStore(id = 10, payload = "managed-pending".toByteArray())
        val owner = owner(outgoing = outgoing)
        val results = mutableListOf<Pair<Boolean, String>>()
        owner.onFileTransferResult = { accepted, reason -> results += accepted to reason }
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
        assertEquals(listOf(false to "policy_denied"), results)
        owner.cancelPreparedOutgoing(prepared.transfer)
        assertEquals(1, outgoing.cancelCount)
        assertEquals(
            FileTransferProductOwner.StartOutgoingResult.Stale(null),
            owner.startPreparedOutgoing(prepared.transfer, canTransferFiles = true),
        )
        assertEquals(1, outgoing.cancelCount)
    }

    @Test
    fun `managed policy denial notifies policy denied for active outgoing transfers`() {
        val outgoing = FakeOutgoingTransferStore(id = 92, payload = "managed-active".toByteArray())
        val owner = owner(outgoing = outgoing)
        val results = mutableListOf<Pair<Boolean, String>>()
        owner.onFileTransferResult = { accepted, reason -> results += accepted to reason }
        owner.activateSession()

        val prepared = owner.prepareOutgoingFile(
            File(stagingDirectory(), "managed-active.txt").also { it.writeText("managed-active") },
            "text/plain",
            FileTransferPolicy(),
        ) as FileTransferProductOwner.PrepareOutgoingResult.Prepared
        assertTrue(owner.startPreparedOutgoing(prepared.transfer, canTransferFiles = true) is FileTransferProductOwner.StartOutgoingResult.Started)

        owner.applyManagedPolicy(
            ProtocolV1Session.ManagedPolicy.UNMANAGED.copy(
                isManaged = true,
                fileTransferAllowed = false,
                maximumFileBytes = 1024,
            ).toStatus(),
        )

        assertEquals(1, outgoing.cancelCount)
        assertEquals(listOf(false to "policy_denied"), results)
    }

    @Test
    fun `start prepared outgoing rejects policy denied when capability unavailable`() {
        val outgoing = FakeOutgoingTransferStore(id = 93, payload = "capability".toByteArray())
        val owner = owner(outgoing = outgoing)
        val results = mutableListOf<Pair<Boolean, String>>()
        owner.onFileTransferResult = { accepted, reason -> results += accepted to reason }
        owner.activateSession()

        val prepared = owner.prepareOutgoingFile(
            File(stagingDirectory(), "capability.txt").also { it.writeText("capability") },
            "text/plain",
            FileTransferPolicy(),
        ) as FileTransferProductOwner.PrepareOutgoingResult.Prepared

        val rejected = owner.startPreparedOutgoing(prepared.transfer, canTransferFiles = false)

        assertTrue(rejected is FileTransferProductOwner.StartOutgoingResult.Rejected)
        assertEquals("policy_denied", (rejected as FileTransferProductOwner.StartOutgoingResult.Rejected).reasonCode)
        assertEquals(1, outgoing.cancelCount)
        assertTrue(results.isEmpty())
    }

    @Test
    fun `start prepared outgoing rejects concurrent limit when another transfer is active`() {
        val owner = owner()
        val results = mutableListOf<Pair<Boolean, String>>()
        owner.onFileTransferResult = { accepted, reason -> results += accepted to reason }
        owner.activateSession()

        val first = owner.prepareOutgoingFile(
            File(stagingDirectory(), "first.txt").also { it.writeText("first") },
            "text/plain",
            FileTransferPolicy(),
        ) as FileTransferProductOwner.PrepareOutgoingResult.Prepared
        val second = owner.prepareOutgoingFile(
            File(stagingDirectory(), "second.txt").also { it.writeText("second") },
            "text/plain",
            FileTransferPolicy(),
        ) as FileTransferProductOwner.PrepareOutgoingResult.Prepared
        assertTrue(owner.startPreparedOutgoing(first.transfer, canTransferFiles = true) is FileTransferProductOwner.StartOutgoingResult.Started)

        val rejected = owner.startPreparedOutgoing(second.transfer, canTransferFiles = true)

        assertTrue(rejected is FileTransferProductOwner.StartOutgoingResult.Rejected)
        assertEquals("concurrent_limit", (rejected as FileTransferProductOwner.StartOutgoingResult.Rejected).reasonCode)
        assertTrue(results.isEmpty())
    }

    @Test
    fun `reject outgoing transfer cancels active transfer and returns reason once`() {
        val outgoing = FakeOutgoingTransferStore(id = 94, payload = "backpressure".toByteArray())
        val owner = owner(outgoing = outgoing)
        owner.activateSession()
        val prepared = owner.prepareOutgoingFile(
            File(stagingDirectory(), "backpressure.txt").also { it.writeText("backpressure") },
            "text/plain",
            FileTransferPolicy(),
        ) as FileTransferProductOwner.PrepareOutgoingResult.Prepared
        val started = owner.startPreparedOutgoing(prepared.transfer, canTransferFiles = true)
        assertTrue(started is FileTransferProductOwner.StartOutgoingResult.Started)
        val transferId = (started as FileTransferProductOwner.StartOutgoingResult.Started).offer.transferId

        val rejected = owner.rejectOutgoingTransfer(
            transferId = transferId,
            prepared = prepared.transfer,
            reasonCode = "outbound_backpressure",
        )
        val duplicate = owner.rejectOutgoingTransfer(
            transferId = transferId,
            prepared = prepared.transfer,
            reasonCode = "outbound_backpressure",
        )

        assertEquals(FileTransferProductOwner.TransferResult(false, "outbound_backpressure"), rejected)
        assertNull(duplicate)
        assertEquals(1, outgoing.cancelCount)
        assertEquals(0, owner.activeOutgoingTransferCount())
    }

    @Test
    fun `reject outgoing transfer returns stored drain reason exactly once`() {
        lateinit var owner: FileTransferProductOwner
        lateinit var prepared: FileTransferProductOwner.PrepareOutgoingResult.Prepared
        lateinit var transferId: ByteString
        val results = mutableListOf<Pair<Boolean, String>>()
        val outgoing = FakeOutgoingTransferStore(id = 96, payload = "drained".toByteArray()) {
            owner.rejectOutgoingTransfer(
                transferId = transferId,
                prepared = prepared.transfer,
                reasonCode = "outbound_backpressure",
            )?.let(owner::notifyFileTransferResult)
        }
        owner = owner(outgoing = outgoing)
        owner.onFileTransferResult = { accepted, reason -> results += accepted to reason }
        owner.activateSession()
        prepared = owner.prepareOutgoingFile(
            File(stagingDirectory(), "drained.txt").also { it.writeText("drained") },
            "text/plain",
            FileTransferPolicy(),
        ) as FileTransferProductOwner.PrepareOutgoingResult.Prepared
        val started = owner.startPreparedOutgoing(prepared.transfer, canTransferFiles = true)
        assertTrue(started is FileTransferProductOwner.StartOutgoingResult.Started)
        transferId = (started as FileTransferProductOwner.StartOutgoingResult.Started).offer.transferId

        owner.clear()

        assertEquals(1, outgoing.cancelCount)
        assertEquals(listOf(false to "connection_cleanup"), results)
        assertNull(
            owner.rejectOutgoingTransfer(
                transferId = transferId,
                prepared = prepared.transfer,
                reasonCode = "outbound_backpressure",
            ),
        )
    }

    @Test
    fun `late outgoing terminal messages after drain do not notify again`() {
        val outgoing = FakeOutgoingTransferStore(id = 97, payload = "late-terminal".toByteArray())
        val owner = owner(outgoing = outgoing)
        val results = mutableListOf<Pair<Boolean, String>>()
        owner.onFileTransferResult = { accepted, reason -> results += accepted to reason }
        owner.activateSession()
        val prepared = owner.prepareOutgoingFile(
            File(stagingDirectory(), "late-terminal.txt").also { it.writeText("late-terminal") },
            "text/plain",
            FileTransferPolicy(),
        ) as FileTransferProductOwner.PrepareOutgoingResult.Prepared
        val started = owner.startPreparedOutgoing(prepared.transfer, canTransferFiles = true)
        assertTrue(started is FileTransferProductOwner.StartOutgoingResult.Started)
        val transferId = (started as FileTransferProductOwner.StartOutgoingResult.Started).offer.transferId

        owner.clear(reasonCode = "session_deactivated")
        owner.handleFileAccept(
            FileAccept.newBuilder()
                .setTransferId(transferId)
                .setAccepted(false)
                .setRejectionReason("host_rejected")
                .build(),
            sessionEpoch = 7,
        ).result?.let(owner::notifyFileTransferResult)
        owner.handleFileProgress(
            FileTransferProgress.newBuilder()
                .setTransferId(transferId)
                .setReceivedBytes(1)
                .build(),
            sessionEpoch = 7,
        ).result?.let(owner::notifyFileTransferResult)
        owner.handleFileCancel(
            FileTransferCancel.newBuilder()
                .setTransferId(transferId)
                .setReasonCode("host_cancelled")
                .build(),
        )?.let(owner::notifyFileTransferResult)
        owner.handleFileComplete(
            FileTransferComplete.newBuilder()
                .setTransferId(transferId)
                .setAccepted(true)
                .setSha256(outgoing.offer.sha256)
                .build(),
        ).result?.let(owner::notifyFileTransferResult)

        assertEquals(1, outgoing.cancelCount)
        assertEquals(listOf(false to "session_deactivated"), results)
    }

    @Test
    fun `file cancel still reports when it cancels an incoming transfer`() {
        val store = FakeIncomingTransferStore(stagingDirectory())
        val owner = owner(store = store)
        owner.activateSession()
        val offer = offer(id = 98, payload = "incoming-cancel".toByteArray())
        assertTrue(
            owner.decideFileOffer(
                offer = offer,
                acceptedByUser = true,
                negotiatedPolicy = FileTransferPolicy(),
                sessionEpoch = 7,
            ).accepted,
        )

        val result = owner.handleFileCancel(
            FileTransferCancel.newBuilder()
                .setTransferId(offer.transferId)
                .setReasonCode("host_cancelled")
                .build(),
        )

        assertEquals(FileTransferProductOwner.TransferResult(false, "host_cancelled"), result)
        assertEquals(listOf(offer.transferId), store.cancelledTransfers)
        assertEquals(0, owner.activeIncomingTransferCount())
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
        assertEquals(
            FileTransferProductOwner.StartOutgoingResult.Stale(null),
            owner.startPreparedOutgoing(prepared.transfer, canTransferFiles = true),
        )
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

        assertTrue(owner.startPreparedOutgoing(prepared.transfer, canTransferFiles = true) is FileTransferProductOwner.StartOutgoingResult.Started)
        assertEquals(
            FileTransferProductOwner.StartOutgoingResult.Stale(null),
            owner.startPreparedOutgoing(prepared.transfer, canTransferFiles = true),
        )
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
        var finishFailure: FileTransferException? = null

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
            finishFailure?.let { throw it }
            val offer = activeOffers.remove(transferId)
                ?: throw FileTransferException("unknown_transfer", "Unknown file transfer")
            val file = File(directory, offer.fileName).also { it.writeBytes(ByteArray(0)) }
            return CompletedIncomingFile(transferId, offer.fileName, offer.mimeType, file, offer.sha256)
        }

        override fun cancel(transferId: ByteString): Boolean {
            val removed = activeOffers.remove(transferId) != null
            cancelledTransfers += transferId
            return removed
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
        private val onCancel: (() -> Unit)? = null,
    ) : FileTransferProductOwner.OutgoingTransferStore {
        override val offer: FileOffer = offer(id = id, payload = payload)
        var cancelCount = 0
            private set

        override fun cancel() {
            cancelCount += 1
            onCancel?.invoke()
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
