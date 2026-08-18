package dev.telemachus.display

/**
 * Clipboard offer advertised by a peer before the content is requested.
 * Contains only metadata; the actual content must be fetched with
 * [StreamClient.requestClipboard] using [changeId].
 */
internal data class ClipboardOfferData(
    val changeId: ByteArray,
    val originDeviceId: String,
    val mimeType: String,
    val byteLength: Long,
    val sha256: ByteArray,
)

/**
 * Clipboard content received from a peer.
 *
 * When [pending] is true the content arrived without a matching
 * offer/request handshake (direct content). The UI must treat it as
 * pending and must never auto-write it to the system clipboard.
 */
internal data class ClipboardContentData(
    val changeId: ByteArray,
    val originDeviceId: String,
    val mimeType: String,
    val content: ByteArray,
    val sha256: ByteArray,
    val pending: Boolean,
)

/**
 * Session-owned UI approval state for clipboard receives.
 *
 * The wire session validates content, while this layer proves that the user
 * approved the exact change on the still-current client generation. Keeping
 * only one pending item bounds retained clipboard content and makes a new offer
 * supersede stale approval from an earlier peer action.
 */
internal class ClipboardApprovalState<ClientIdentity : Any> {
    private var owner: Owner<ClientIdentity>? = null
    private var pendingOffer: PendingClipboardOffer? = null
    private var pendingDirectContent: ClipboardContentData? = null
    private var approvedChangeId: ByteArray? = null

    fun activate(client: ClientIdentity, generation: Long) {
        owner = Owner(client, generation)
        clearPending()
    }

    fun clear() {
        owner = null
        clearPending()
    }

    fun stageOffer(
        client: ClientIdentity,
        generation: Long,
        offer: PendingClipboardOffer,
    ): Boolean {
        if (!matches(client, generation)) return false
        pendingOffer = offer
        pendingDirectContent = null
        approvedChangeId = null
        return true
    }

    fun stageDirectContent(
        client: ClientIdentity,
        generation: Long,
        content: ClipboardContentData,
    ): Boolean {
        if (!matches(client, generation) || !content.pending) return false
        val approved = approvedChangeId
        if (approved != null && !approved.contentEquals(content.changeId)) return false
        val offer = pendingOffer
        if (offer != null && !offer.changeId.contentEquals(content.changeId)) return false
        pendingOffer = null
        pendingDirectContent = content
        approvedChangeId = null
        return true
    }

    fun offerForRequest(
        client: ClientIdentity,
        generation: Long,
    ): PendingClipboardOffer? =
        if (matches(client, generation) && approvedChangeId == null) pendingOffer else null

    fun directContentForConfirmation(
        client: ClientIdentity,
        generation: Long,
    ): ClipboardContentData? =
        if (matches(client, generation)) pendingDirectContent else null

    fun approveOffer(
        client: ClientIdentity,
        generation: Long,
        changeId: ByteArray,
    ): Boolean {
        val offer = offerForRequest(client, generation) ?: return false
        if (!offer.changeId.contentEquals(changeId)) return false
        approvedChangeId = changeId.copyOf()
        return true
    }

    fun cancelOfferApproval(
        client: ClientIdentity,
        generation: Long,
        changeId: ByteArray,
    ): Boolean {
        if (matches(client, generation) && approvedChangeId?.contentEquals(changeId) == true) {
            approvedChangeId = null
            return true
        }
        return false
    }

    fun consumeSolicitedContent(
        client: ClientIdentity,
        generation: Long,
        content: ClipboardContentData,
    ): ClipboardContentData? {
        if (!matches(client, generation) || content.pending) return null
        if (approvedChangeId?.contentEquals(content.changeId) != true) return null
        val offer = pendingOffer ?: return null
        if (!offer.changeId.contentEquals(content.changeId)) return null
        clearPending()
        return content
    }

    fun consumeDirectContent(
        client: ClientIdentity,
        generation: Long,
        changeId: ByteArray,
    ): ClipboardContentData? {
        if (!matches(client, generation)) return null
        val content = pendingDirectContent ?: return null
        if (!content.changeId.contentEquals(changeId)) return null
        clearPending()
        return content
    }

    fun discardDirectContent(
        client: ClientIdentity,
        generation: Long,
        changeId: ByteArray,
    ) {
        if (matches(client, generation) && pendingDirectContent?.changeId?.contentEquals(changeId) == true) {
            clearPending()
        }
    }

    fun hasPendingReceive(
        client: ClientIdentity,
        generation: Long,
    ): Boolean =
        matches(client, generation) &&
            ((pendingOffer != null && approvedChangeId == null) || pendingDirectContent != null)

    private fun matches(client: ClientIdentity, generation: Long): Boolean =
        owner?.let { it.client === client && it.generation == generation } == true

    private fun clearPending() {
        pendingOffer = null
        pendingDirectContent = null
        approvedChangeId = null
    }

    private data class Owner<ClientIdentity : Any>(
        val client: ClientIdentity,
        val generation: Long,
    )
}
