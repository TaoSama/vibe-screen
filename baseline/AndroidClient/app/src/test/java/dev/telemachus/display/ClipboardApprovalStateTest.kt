package dev.telemachus.display

import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

class ClipboardApprovalStateTest {
    @Test
    fun `solicited content is consumed only after exact current generation approval`() {
        val state = ClipboardApprovalState<Any>()
        val owner = Any()
        val staleOwner = Any()
        val changeId = ByteArray(16) { 1 }
        val offer = offer(changeId)
        val content = content(changeId, pending = false)
        state.activate(owner, generation = 3)

        assertFalse(state.stageOffer(staleOwner, generation = 3, offer))
        assertTrue(state.stageOffer(owner, generation = 3, offer))
        assertNull(state.consumeSolicitedContent(owner, generation = 3, content))
        assertFalse(state.approveOffer(owner, generation = 2, changeId))
        assertTrue(state.approveOffer(owner, generation = 3, changeId))
        assertNull(state.consumeSolicitedContent(owner, generation = 2, content))
        assertSame(content, state.consumeSolicitedContent(owner, generation = 3, content))
        assertFalse(state.hasPendingReceive(owner, generation = 3))
        assertNull(state.consumeSolicitedContent(owner, generation = 3, content))
    }

    @Test
    fun `direct content remains pending until separately confirmed`() {
        val state = ClipboardApprovalState<Any>()
        val owner = Any()
        val changeId = ByteArray(16) { 2 }
        val direct = content(changeId, pending = true)
        state.activate(owner, generation = 9)

        assertTrue(state.stageDirectContent(owner, generation = 9, direct))
        assertTrue(state.hasPendingReceive(owner, generation = 9))
        assertNull(state.consumeDirectContent(owner, generation = 8, changeId))
        assertNull(state.consumeDirectContent(owner, generation = 9, ByteArray(16)))
        assertSame(direct, state.consumeDirectContent(owner, generation = 9, changeId))
        assertFalse(state.hasPendingReceive(owner, generation = 9))
    }

    @Test
    fun `new session owner invalidates all pending approval`() {
        val state = ClipboardApprovalState<Any>()
        val oldOwner = Any()
        val newOwner = Any()
        val changeId = ByteArray(16) { 3 }
        state.activate(oldOwner, generation = 1)
        assertTrue(state.stageOffer(oldOwner, generation = 1, offer(changeId)))
        assertTrue(state.approveOffer(oldOwner, generation = 1, changeId))

        state.activate(newOwner, generation = 2)

        assertFalse(state.hasPendingReceive(oldOwner, generation = 1))
        assertFalse(state.hasPendingReceive(newOwner, generation = 2))
        assertNull(state.consumeSolicitedContent(oldOwner, generation = 1, content(changeId, pending = false)))
    }

    @Test
    fun `clipboard menu enforces local and peer limits in UTF8 bytes`() {
        assertFalse(ClipboardMenuPolicy.isAvailable(clipboard = false))
        assertTrue(ClipboardMenuPolicy.isAvailable(clipboard = true))
        assertFalse(ClipboardMenuPolicy.canSend(null))
        assertFalse(ClipboardMenuPolicy.canSend(""))
        assertTrue(ClipboardMenuPolicy.canSend("text"))

        assertTrue(ClipboardMenuPolicy.isWithinSizeLimit("é", maximumClipboardBytes = 2))
        assertFalse(ClipboardMenuPolicy.isWithinSizeLimit("é", maximumClipboardBytes = 1))
        assertFalse(
            ClipboardMenuPolicy.isWithinSizeLimit(
                "a".repeat((ClipboardMenuPolicy.DEFAULT_CLIPBOARD_BYTES + 1).toInt()),
                maximumClipboardBytes = Long.MAX_VALUE,
            ),
        )
    }

    @Test
    fun approvedOfferDisablesDuplicateReceiveUntilContentArrives() {
        val state = ClipboardApprovalState<Any>()
        val owner = Any()
        val changeId = ByteArray(16) { 4 }
        state.activate(owner, generation = 4)
        assertTrue(state.stageOffer(owner, generation = 4, offer(changeId)))

        assertTrue(state.approveOffer(owner, generation = 4, changeId))

        assertFalse(state.hasPendingReceive(owner, generation = 4))
        assertNull(state.offerForRequest(owner, generation = 4))
    }

    @Test
    fun directContentCannotReplaceAnApprovedInFlightOffer() {
        val state = ClipboardApprovalState<Any>()
        val owner = Any()
        val offeredChangeId = ByteArray(16) { 4 }
        val directChangeId = ByteArray(16) { 5 }
        val solicited = content(offeredChangeId, pending = false)
        state.activate(owner, generation = 4)
        assertTrue(state.stageOffer(owner, generation = 4, offer(offeredChangeId)))
        assertTrue(state.approveOffer(owner, generation = 4, offeredChangeId))

        assertFalse(
            state.stageDirectContent(
                owner,
                generation = 4,
                content(directChangeId, pending = true),
            ),
        )
        assertSame(solicited, state.consumeSolicitedContent(owner, generation = 4, solicited))
        assertFalse(state.hasPendingReceive(owner, generation = 4))
    }

    @Test
    fun requestTimeoutRestoresOnlyTheExactCurrentOffer() {
        val state = ClipboardApprovalState<Any>()
        val owner = Any()
        val staleOwner = Any()
        val changeId = ByteArray(16) { 4 }
        state.activate(owner, generation = 4)
        assertTrue(state.stageOffer(owner, generation = 4, offer(changeId)))
        assertTrue(state.approveOffer(owner, generation = 4, changeId))

        assertFalse(state.cancelOfferApproval(staleOwner, generation = 4, changeId))
        assertFalse(state.cancelOfferApproval(owner, generation = 3, changeId))
        assertFalse(state.cancelOfferApproval(owner, generation = 4, ByteArray(16)))
        assertFalse(state.hasPendingReceive(owner, generation = 4))

        assertTrue(state.cancelOfferApproval(owner, generation = 4, changeId))
        assertTrue(state.hasPendingReceive(owner, generation = 4))
        assertTrue(state.offerForRequest(owner, generation = 4)?.changeId?.contentEquals(changeId) == true)
    }

    @Test
    fun newOfferReplacesAnApprovedStaleOffer() {
        val state = ClipboardApprovalState<Any>()
        val owner = Any()
        val oldChangeId = ByteArray(16) { 5 }
        val newChangeId = ByteArray(16) { 6 }
        state.activate(owner, generation = 5)
        assertTrue(state.stageOffer(owner, generation = 5, offer(oldChangeId)))
        assertTrue(state.approveOffer(owner, generation = 5, oldChangeId))

        assertTrue(state.stageOffer(owner, generation = 5, offer(newChangeId)))

        assertTrue(state.hasPendingReceive(owner, generation = 5))
        assertNull(
            state.consumeSolicitedContent(
                owner,
                generation = 5,
                content(oldChangeId, pending = false),
            ),
        )
        assertTrue(state.approveOffer(owner, generation = 5, newChangeId))
    }


    @Test
    fun `non-positive negotiated limit falls back to local 1 MiB`() {
        val oneMiB = "a".repeat(ClipboardMenuPolicy.DEFAULT_CLIPBOARD_BYTES.toInt())
        val oneMiBPlusOne = "a".repeat((ClipboardMenuPolicy.DEFAULT_CLIPBOARD_BYTES + 1).toInt())

        for (limit in listOf(0L, -1L, Long.MIN_VALUE)) {
            assertTrue(
                ClipboardMenuPolicy.isWithinSizeLimit(oneMiB, maximumClipboardBytes = limit),
            )
            assertFalse(
                ClipboardMenuPolicy.isWithinSizeLimit(oneMiBPlusOne, maximumClipboardBytes = limit),
            )
        }
    }

    @Test
    fun `exactly 1 MiB is accepted and one byte over is rejected`() {
        val oneMiB = "a".repeat(ClipboardMenuPolicy.DEFAULT_CLIPBOARD_BYTES.toInt())
        val oneMiBPlusOne = "a".repeat((ClipboardMenuPolicy.DEFAULT_CLIPBOARD_BYTES + 1).toInt())

        assertTrue(
            ClipboardMenuPolicy.isWithinSizeLimit(
                oneMiB,
                maximumClipboardBytes = ClipboardMenuPolicy.DEFAULT_CLIPBOARD_BYTES,
            ),
        )
        assertFalse(
            ClipboardMenuPolicy.isWithinSizeLimit(
                oneMiBPlusOne,
                maximumClipboardBytes = ClipboardMenuPolicy.DEFAULT_CLIPBOARD_BYTES,
            ),
        )
        // A peer limit larger than the local cap is still clamped to 1 MiB.
        assertTrue(
            ClipboardMenuPolicy.isWithinSizeLimit(oneMiB, maximumClipboardBytes = Long.MAX_VALUE),
        )
        assertFalse(
            ClipboardMenuPolicy.isWithinSizeLimit(
                oneMiBPlusOne,
                maximumClipboardBytes = Long.MAX_VALUE,
            ),
        )
    }

    @Test
    fun `clear invalidates owner and all pending state`() {
        val state = ClipboardApprovalState<Any>()
        val owner = Any()
        val changeId = ByteArray(16) { 7 }
        state.activate(owner, generation = 1)
        assertTrue(state.stageOffer(owner, generation = 1, offer(changeId)))
        assertTrue(state.hasPendingReceive(owner, generation = 1))

        state.clear()

        assertFalse(state.stageOffer(owner, generation = 1, offer(changeId)))
        assertFalse(state.stageDirectContent(owner, generation = 1, content(changeId, pending = true)))
        assertFalse(state.hasPendingReceive(owner, generation = 1))
        assertNull(state.consumeSolicitedContent(owner, generation = 1, content(changeId, pending = false)))
        assertNull(state.consumeDirectContent(owner, generation = 1, changeId))
    }

    @Test
    fun `direct content discard and consume require exact change id`() {
        val state = ClipboardApprovalState<Any>()
        val owner = Any()
        val changeId = ByteArray(16) { 8 }
        val wrongChangeId = ByteArray(16) { 9 }
        val direct = content(changeId, pending = true)
        state.activate(owner, generation = 2)
        assertTrue(state.stageDirectContent(owner, generation = 2, direct))

        assertNull(state.consumeDirectContent(owner, generation = 2, wrongChangeId))
        assertTrue(state.hasPendingReceive(owner, generation = 2))

        state.discardDirectContent(owner, generation = 2, wrongChangeId)
        assertTrue(state.hasPendingReceive(owner, generation = 2))

        assertSame(direct, state.consumeDirectContent(owner, generation = 2, changeId))
        assertFalse(state.hasPendingReceive(owner, generation = 2))
    }

    @Test
    fun `new offer replaces pending direct content and direct content cannot replace an offer`() {
        val state = ClipboardApprovalState<Any>()
        val owner = Any()
        val offerChangeId = ByteArray(16) { 10 }
        val directChangeId = ByteArray(16) { 11 }
        state.activate(owner, generation = 3)

        // Direct content staged first; a later offer clears it.
        assertTrue(state.stageDirectContent(owner, generation = 3, content(directChangeId, pending = true)))
        assertTrue(state.stageOffer(owner, generation = 3, offer(offerChangeId)))
        assertNull(state.directContentForConfirmation(owner, generation = 3))
        assertTrue(state.hasPendingReceive(owner, generation = 3))

        // Offer staged first; direct content cannot displace the explicit pull path.
        assertFalse(state.stageDirectContent(owner, generation = 3, content(directChangeId, pending = true)))
        assertTrue(state.offerForRequest(owner, generation = 3)?.changeId?.contentEquals(offerChangeId) == true)
        assertNull(state.directContentForConfirmation(owner, generation = 3))
    }

    @Test
    fun `late direct content for a superseded request cannot replace the newer offer`() {
        val state = ClipboardApprovalState<Any>()
        val owner = Any()
        val oldChangeId = ByteArray(16) { 12 }
        val newChangeId = ByteArray(16) { 13 }
        state.activate(owner, generation = 6)
        assertTrue(state.stageOffer(owner, generation = 6, offer(oldChangeId)))
        assertTrue(state.approveOffer(owner, generation = 6, oldChangeId))
        assertTrue(state.stageOffer(owner, generation = 6, offer(newChangeId)))

        assertFalse(
            state.stageDirectContent(
                owner,
                generation = 6,
                content(oldChangeId, pending = true),
            ),
        )
        assertTrue(state.offerForRequest(owner, generation = 6)?.changeId?.contentEquals(newChangeId) == true)
        assertNull(state.directContentForConfirmation(owner, generation = 6))
    }

    @Test
    fun `late direct content for the same timed out offer can require confirmation`() {
        val state = ClipboardApprovalState<Any>()
        val owner = Any()
        val changeId = ByteArray(16) { 14 }
        val lateContent = content(changeId, pending = true)
        state.activate(owner, generation = 7)
        assertTrue(state.stageOffer(owner, generation = 7, offer(changeId)))
        assertTrue(state.approveOffer(owner, generation = 7, changeId))
        assertTrue(state.cancelOfferApproval(owner, generation = 7, changeId))

        assertTrue(state.stageDirectContent(owner, generation = 7, lateContent))
        assertSame(lateContent, state.directContentForConfirmation(owner, generation = 7))
        assertNull(state.offerForRequest(owner, generation = 7))
    }

    @Test
    fun `same id direct content closes the timeout handoff window without auto applying`() {
        val state = ClipboardApprovalState<Any>()
        val owner = Any()
        val changeId = ByteArray(16) { 15 }
        val lateContent = content(changeId, pending = true)
        state.activate(owner, generation = 8)
        assertTrue(state.stageOffer(owner, generation = 8, offer(changeId)))
        assertTrue(state.approveOffer(owner, generation = 8, changeId))

        assertTrue(state.stageDirectContent(owner, generation = 8, lateContent))
        assertFalse(state.cancelOfferApproval(owner, generation = 8, changeId))
        assertSame(lateContent, state.directContentForConfirmation(owner, generation = 8))
        assertTrue(state.hasPendingReceive(owner, generation = 8))
    }

    private fun offer(changeId: ByteArray) =
        PendingClipboardOffer(
            changeId = changeId,
            originDeviceId = "mac",
            mimeType = "text/plain",
            byteLength = 4,
            sha256 = ByteArray(32) { 7 },
        )

    private fun content(changeId: ByteArray, pending: Boolean) =
        ClipboardContentData(
            changeId = changeId,
            originDeviceId = "mac",
            mimeType = "text/plain",
            content = "text".toByteArray(),
            sha256 = ByteArray(32) { 7 },
            pending = pending,
        )
}
