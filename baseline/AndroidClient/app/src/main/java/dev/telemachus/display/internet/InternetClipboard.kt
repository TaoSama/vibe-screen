package dev.telemachus.display.internet

import com.google.protobuf.ByteString
import dev.telemachus.display.ClipboardContentData
import dev.telemachus.display.ClipboardOfferData
import dev.vibescreen.protocol.v1.ClipboardContent
import dev.vibescreen.protocol.v1.ClipboardOffer
import dev.vibescreen.protocol.v1.ClipboardRequest
import dev.vibescreen.protocol.v1.ManagedPolicyStatus
import dev.vibescreen.protocol.v1.ManagedRestrictionResult
import java.nio.ByteBuffer
import java.nio.charset.CharacterCodingException
import java.nio.charset.CodingErrorAction
import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.ArrayDeque

internal class InternetClipboard(
    private val localDeviceId: String,
    private val remoteDeviceId: String,
    private val maximumBytes: Long,
    private val random: SecureRandom = SecureRandom(),
) {
    private data class LocalSnapshot(
        val changeId: ByteString,
        val content: ByteArray,
        val sha256: ByteString,
        var consumed: Boolean = false,
    )

    private data class RemoteOffer(
        val changeId: ByteString,
        val originDeviceId: String,
        val mimeType: String,
        val byteLength: Long,
        val sha256: ByteString,
    )

    private var localSnapshot: LocalSnapshot? = null
    private var pendingOffer: RemoteOffer? = null
    private var pendingRequest: ByteString? = null
    private val seenChangeIds = ArrayDeque<ByteString>()

    init {
        require(localDeviceId.isNotBlank() && remoteDeviceId.isNotBlank()) { "Clipboard identities are required" }
        require(maximumBytes in 1..LOCAL_MAX_CLIPBOARD_BYTES) { "Clipboard byte limit is invalid" }
    }

    fun prepareOffer(text: String): ClipboardOffer? {
        val bytes = text.toByteArray(StandardCharsets.UTF_8)
        if (bytes.isEmpty() || bytes.size.toLong() > maximumBytes) return null
        val changeId = ByteString.copyFrom(ByteArray(CLIPBOARD_CHANGE_ID_BYTES).also(random::nextBytes))
        val sha256 = ByteString.copyFrom(sha256(bytes))
        remember(changeId)
        localSnapshot = LocalSnapshot(changeId, bytes.copyOf(), sha256)
        return ClipboardOffer
            .newBuilder()
            .setChangeId(changeId)
            .setOriginDeviceId(localDeviceId)
            .setMimeType(CLIPBOARD_MIME_TEXT_PLAIN)
            .setByteLength(bytes.size.toLong())
            .setSha256(sha256)
            .build()
    }

    fun requestContent(changeId: ByteArray): ClipboardRequest? {
        val id = ByteString.copyFrom(changeId)
        val offer = pendingOffer ?: return null
        if (offer.changeId != id || pendingRequest == id) return null
        pendingRequest = id
        return ClipboardRequest.newBuilder().setChangeId(id).build()
    }

    fun expireRequest(changeId: ByteArray): Boolean {
        val id = ByteString.copyFrom(changeId)
        if (pendingRequest != id) return false
        pendingRequest = null
        return true
    }

    fun makeContent(request: ClipboardRequest): ClipboardContent? {
        require(request.changeId.size() == CLIPBOARD_CHANGE_ID_BYTES) { "Invalid clipboard request change_id length" }
        val snapshot = localSnapshot ?: return null
        if (snapshot.changeId != request.changeId || snapshot.consumed) return null
        snapshot.consumed = true
        localSnapshot = snapshot
        return ClipboardContent
            .newBuilder()
            .setChangeId(snapshot.changeId)
            .setOriginDeviceId(localDeviceId)
            .setMimeType(CLIPBOARD_MIME_TEXT_PLAIN)
            .setContent(ByteString.copyFrom(snapshot.content))
            .setSha256(snapshot.sha256)
            .build()
    }

    fun handleOffer(offer: ClipboardOffer): ClipboardOfferData {
        require(offer.originDeviceId == remoteDeviceId) { "ClipboardOffer origin_device_id does not match host id" }
        require(offer.changeId.size() == CLIPBOARD_CHANGE_ID_BYTES) { "Invalid clipboard change_id length" }
        require(offer.changeId !in seenChangeIds) { "ClipboardOffer change_id is a loopback" }
        require(offer.mimeType == CLIPBOARD_MIME_TEXT_PLAIN) { "Unsupported clipboard mime type" }
        require(offer.byteLength in 1..maximumBytes) { "Invalid clipboard byte_length" }
        require(offer.sha256.size() == CLIPBOARD_SHA256_BYTES) { "Invalid clipboard sha256 length" }
        val candidate = RemoteOffer(
            changeId = offer.changeId,
            originDeviceId = offer.originDeviceId,
            mimeType = offer.mimeType,
            byteLength = offer.byteLength,
            sha256 = offer.sha256,
        )
        val existing = pendingOffer
        if (existing != null && existing.changeId == candidate.changeId) {
            require(existing == candidate) { "ClipboardOffer metadata changed for an existing change_id" }
            return existing.toData()
        }
        pendingOffer = candidate
        pendingRequest = null
        return candidate.toData()
    }

    fun handleContent(content: ClipboardContent): ClipboardContentData {
        require(content.originDeviceId == remoteDeviceId) { "ClipboardContent origin_device_id does not match host id" }
        require(content.changeId.size() == CLIPBOARD_CHANGE_ID_BYTES) { "Invalid clipboard content change_id length" }
        require(content.changeId !in seenChangeIds) { "ClipboardContent change_id was already sent or accepted" }
        require(content.mimeType == CLIPBOARD_MIME_TEXT_PLAIN) { "Unsupported clipboard content mime type" }
        val bytes = content.content.toByteArray()
        require(bytes.isNotEmpty()) { "ClipboardContent content is empty" }
        require(bytes.size.toLong() <= maximumBytes) { "ClipboardContent exceeds negotiated limit" }
        validateUtf8(bytes)
        require(content.sha256.size() == CLIPBOARD_SHA256_BYTES) { "Invalid clipboard content sha256 length" }
        require(ByteString.copyFrom(sha256(bytes)) == content.sha256) { "ClipboardContent sha256 mismatch" }

        val solicited = pendingRequest == content.changeId
        if (solicited) {
            val offer = pendingOffer ?: throw IllegalArgumentException("ClipboardContent matches request but no offer is cached")
            require(offer.changeId == content.changeId) { "ClipboardContent request does not match offer" }
            require(offer.byteLength == bytes.size.toLong()) { "ClipboardContent byte_length does not match offer" }
            require(offer.sha256 == content.sha256) { "ClipboardContent sha256 does not match offer" }
            require(offer.originDeviceId == content.originDeviceId && offer.mimeType == content.mimeType) {
                "ClipboardContent identity does not match offer"
            }
            pendingOffer = null
            pendingRequest = null
            remember(content.changeId)
        }
        return ClipboardContentData(
            changeId = content.changeId.toByteArray(),
            originDeviceId = content.originDeviceId,
            mimeType = content.mimeType,
            content = bytes,
            sha256 = content.sha256.toByteArray(),
            pending = !solicited,
        )
    }

    fun reset() {
        localSnapshot = null
        pendingOffer = null
        pendingRequest = null
        seenChangeIds.clear()
    }

    private fun RemoteOffer.toData(): ClipboardOfferData =
        ClipboardOfferData(
            changeId = changeId.toByteArray(),
            originDeviceId = originDeviceId,
            mimeType = mimeType,
            byteLength = byteLength,
            sha256 = sha256.toByteArray(),
        )

    private fun remember(changeId: ByteString) {
        if (changeId in seenChangeIds) return
        seenChangeIds.addLast(changeId)
        while (seenChangeIds.size > MAX_CLIPBOARD_SEEN_IDS) {
            seenChangeIds.removeFirst()
        }
    }

    private fun validateUtf8(bytes: ByteArray) {
        val decoder = StandardCharsets.UTF_8.newDecoder()
            .onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT)
        try {
            decoder.decode(ByteBuffer.wrap(bytes))
        } catch (failure: CharacterCodingException) {
            throw IllegalArgumentException("Clipboard content is not valid UTF-8", failure)
        }
    }

    companion object {
        const val LOCAL_MAX_CLIPBOARD_BYTES: Long = 1_024L * 1_024L
        const val CLIPBOARD_CHANGE_ID_BYTES = 16
        const val CLIPBOARD_SHA256_BYTES = 32
        const val CLIPBOARD_MIME_TEXT_PLAIN = "text/plain"
        private const val MAX_CLIPBOARD_SEEN_IDS = 128

        fun sha256(bytes: ByteArray): ByteArray = MessageDigest.getInstance("SHA-256").digest(bytes)
    }
}

internal data class InternetManagedRestrictionResult(
    val restriction: String,
    val allowed: Boolean,
    val source: String,
    val reason: String,
) {
    fun toProtocol(): ManagedRestrictionResult =
        ManagedRestrictionResult.newBuilder()
            .setRestriction(restriction)
            .setAllowed(allowed)
            .setSource(source)
            .setReason(reason)
            .build()
}

internal data class InternetManagedPolicy(
    val isManaged: Boolean,
    val clipboardAllowed: Boolean,
    val fileTransferAllowed: Boolean,
    val audioAllowed: Boolean,
    val wakeAllowed: Boolean,
    val customGesturesAllowed: Boolean,
    val hostActionsAllowed: Boolean,
    val maximumFileBytes: Long,
    val allowedHosts: Set<String>,
    val allowedHostsRestricted: Boolean = allowedHosts.isNotEmpty(),
    val deniedHosts: Set<String> = emptySet(),
    val restrictionResults: List<InternetManagedRestrictionResult>? = null,
) {
    private val normalizedAllowedHosts = allowedHosts.mapNotNull(::normalizeHost).toSet()
    private val normalizedDeniedHosts = deniedHosts.mapNotNull(::normalizeHost).toSet()
    val effectiveAllowedHostsRestricted = allowedHostsRestricted || normalizedAllowedHosts.isNotEmpty()
    val effectiveFileTransferAllowed = fileTransferAllowed && maximumFileBytes > 0L
    val effectiveRestrictionResults = restrictionResults ?: results(
        source = if (isManaged) "managed_configuration" else "unmanaged",
        reason = if (isManaged) "Local managed configuration result." else "No local managed configuration is present.",
        clipboardAllowed = clipboardAllowed,
        fileTransferAllowed = effectiveFileTransferAllowed,
        audioAllowed = audioAllowed,
        wakeAllowed = wakeAllowed,
        customGesturesAllowed = customGesturesAllowed,
        hostActionsAllowed = hostActionsAllowed,
        maximumFileBytes = maximumFileBytes,
        allowedHostsRestricted = effectiveAllowedHostsRestricted,
        allowedHosts = normalizedAllowedHosts,
        deniedHosts = normalizedDeniedHosts,
    )

    fun applying(remote: InternetManagedPolicy): InternetManagedPolicy {
        if (!remote.isManaged) return this
        val restricted = effectiveAllowedHostsRestricted || remote.effectiveAllowedHostsRestricted
        val hosts = when {
            effectiveAllowedHostsRestricted && remote.effectiveAllowedHostsRestricted -> normalizedAllowedHosts.intersect(remote.normalizedAllowedHosts)
            effectiveAllowedHostsRestricted -> normalizedAllowedHosts
            remote.effectiveAllowedHostsRestricted -> remote.normalizedAllowedHosts
            else -> emptySet()
        }
        val denied = normalizedDeniedHosts + remote.normalizedDeniedHosts
        val allowed = hosts - denied
        val maxFileBytes = minOf(maximumFileBytes, remote.maximumFileBytes)
        val filesAllowed = effectiveFileTransferAllowed && remote.effectiveFileTransferAllowed && maxFileBytes > 0L
        return InternetManagedPolicy(
            isManaged = true,
            clipboardAllowed = clipboardAllowed && remote.clipboardAllowed,
            fileTransferAllowed = filesAllowed,
            audioAllowed = audioAllowed && remote.audioAllowed,
            wakeAllowed = wakeAllowed && remote.wakeAllowed,
            customGesturesAllowed = customGesturesAllowed && remote.customGesturesAllowed,
            hostActionsAllowed = hostActionsAllowed && remote.hostActionsAllowed,
            maximumFileBytes = maxFileBytes,
            allowedHosts = allowed,
            allowedHostsRestricted = restricted,
            deniedHosts = denied,
            restrictionResults = results(
                source = "effective_deny_wins",
                reason = "Local and remote managed policy were combined with deny-wins semantics.",
                clipboardAllowed = clipboardAllowed && remote.clipboardAllowed,
                fileTransferAllowed = filesAllowed,
                audioAllowed = audioAllowed && remote.audioAllowed,
                wakeAllowed = wakeAllowed && remote.wakeAllowed,
                customGesturesAllowed = customGesturesAllowed && remote.customGesturesAllowed,
                hostActionsAllowed = hostActionsAllowed && remote.hostActionsAllowed,
                maximumFileBytes = maxFileBytes,
                allowedHostsRestricted = restricted,
                allowedHosts = allowed,
                deniedHosts = denied,
            ),
        )
    }

    fun allowsHost(hostId: String): Boolean {
        val normalized = normalizeHost(hostId)
        if (normalized != null && normalized in normalizedDeniedHosts) return false
        return !effectiveAllowedHostsRestricted || (normalized != null && normalized in normalizedAllowedHosts)
    }

    fun toStatus(): ManagedPolicyStatus =
        ManagedPolicyStatus.newBuilder()
            .setManaged(isManaged)
            .setClipboardAllowed(clipboardAllowed)
            .setFileTransferAllowed(effectiveFileTransferAllowed)
            .setAudioAllowed(audioAllowed)
            .setWakeAllowed(wakeAllowed)
            .setCustomGesturesAllowed(customGesturesAllowed)
            .setHostActionsAllowed(hostActionsAllowed)
            .setMaximumFileBytes(maximumFileBytes)
            .addAllAllowedHosts(normalizedAllowedHosts.sorted())
            .setAllowedHostsRestricted(effectiveAllowedHostsRestricted)
            .addAllRestrictionResults(effectiveRestrictionResults.map { it.toProtocol() })
            .addAllDeniedHosts(normalizedDeniedHosts.sorted())
            .build()

    companion object {
        const val DEFAULT_MAXIMUM_FILE_BYTES = 512L * 1_024L * 1_024L
        private const val RESTRICTION_CLIPBOARD = "clipboard"
        private const val RESTRICTION_FILE_TRANSFER = "file_transfer"
        private const val RESTRICTION_AUDIO = "audio"
        private const val RESTRICTION_WAKE = "wake"
        private const val RESTRICTION_CUSTOM_GESTURES = "custom_gestures"
        private const val RESTRICTION_HOST_ACTIONS = "host_actions"
        private const val RESTRICTION_MAXIMUM_FILE_BYTES = "maximum_file_bytes"
        private const val RESTRICTION_ALLOWED_HOSTS = "allowed_hosts"
        private const val RESTRICTION_DENIED_HOSTS = "denied_hosts"
        private val REQUIRED_RESTRICTIONS = setOf(
            RESTRICTION_CLIPBOARD,
            RESTRICTION_FILE_TRANSFER,
            RESTRICTION_AUDIO,
            RESTRICTION_WAKE,
            RESTRICTION_CUSTOM_GESTURES,
            RESTRICTION_HOST_ACTIONS,
            RESTRICTION_MAXIMUM_FILE_BYTES,
            RESTRICTION_ALLOWED_HOSTS,
            RESTRICTION_DENIED_HOSTS,
        )

        val UNMANAGED = InternetManagedPolicy(
            isManaged = false,
            clipboardAllowed = true,
            fileTransferAllowed = true,
            audioAllowed = true,
            wakeAllowed = true,
            customGesturesAllowed = true,
            hostActionsAllowed = true,
            maximumFileBytes = DEFAULT_MAXIMUM_FILE_BYTES,
            allowedHosts = emptySet(),
            allowedHostsRestricted = false,
        )

        fun fromStatus(status: ManagedPolicyStatus): InternetManagedPolicy {
            if (!status.managed) return UNMANAGED
            val results = status.restrictionResultsList.map { result ->
                InternetManagedRestrictionResult(
                    restriction = result.restriction,
                    allowed = result.allowed,
                    source = result.source,
                    reason = result.reason,
                )
            }
            return InternetManagedPolicy(
                isManaged = true,
                clipboardAllowed = status.clipboardAllowed,
                fileTransferAllowed = status.fileTransferAllowed,
                audioAllowed = status.audioAllowed,
                wakeAllowed = status.wakeAllowed,
                customGesturesAllowed = status.customGesturesAllowed,
                hostActionsAllowed = status.hostActionsAllowed,
                maximumFileBytes = status.maximumFileBytes,
                allowedHosts = status.allowedHostsList.toSet(),
                allowedHostsRestricted = status.allowedHostsRestricted || status.allowedHostsList.isNotEmpty(),
                deniedHosts = status.deniedHostsList.toSet(),
                restrictionResults = results.ifEmpty { null },
            )
        }

        fun hasCompleteRestrictionResults(status: ManagedPolicyStatus): Boolean {
            if (!status.managed) return true
            val results = status.restrictionResultsList
            if (results.size != REQUIRED_RESTRICTIONS.size) return false
            if (results.map { it.restriction }.toSet() != REQUIRED_RESTRICTIONS) return false
            if (results.groupingBy { it.restriction }.eachCount().values.any { it != 1 }) return false
            val allowedHosts = status.allowedHostsList.mapNotNull(::normalizeHost).toSet()
            val deniedHosts = status.deniedHostsList.mapNotNull(::normalizeHost).toSet()
            return results.all { result ->
                result.source.isNotBlank() && result.reason.isNotBlank() &&
                    result.allowed == when (result.restriction) {
                        RESTRICTION_CLIPBOARD -> status.clipboardAllowed
                        RESTRICTION_FILE_TRANSFER -> status.fileTransferAllowed && status.maximumFileBytes > 0L
                        RESTRICTION_AUDIO -> status.audioAllowed
                        RESTRICTION_WAKE -> status.wakeAllowed
                        RESTRICTION_CUSTOM_GESTURES -> status.customGesturesAllowed
                        RESTRICTION_HOST_ACTIONS -> status.hostActionsAllowed
                        RESTRICTION_MAXIMUM_FILE_BYTES -> status.maximumFileBytes > 0L
                        RESTRICTION_ALLOWED_HOSTS -> {
                            val restricted = status.allowedHostsRestricted || allowedHosts.isNotEmpty()
                            !restricted || (allowedHosts - deniedHosts).isNotEmpty()
                        }
                        RESTRICTION_DENIED_HOSTS -> deniedHosts.isEmpty()
                        else -> false
                    }
            }
        }

        private fun results(
            source: String,
            reason: String,
            clipboardAllowed: Boolean,
            fileTransferAllowed: Boolean,
            audioAllowed: Boolean,
            wakeAllowed: Boolean,
            customGesturesAllowed: Boolean,
            hostActionsAllowed: Boolean,
            maximumFileBytes: Long,
            allowedHostsRestricted: Boolean,
            allowedHosts: Set<String>,
            deniedHosts: Set<String>,
        ): List<InternetManagedRestrictionResult> {
            val effectiveAllowedHosts = allowedHosts - deniedHosts
            return listOf(
                InternetManagedRestrictionResult(RESTRICTION_CLIPBOARD, clipboardAllowed, source, reason),
                InternetManagedRestrictionResult(RESTRICTION_FILE_TRANSFER, fileTransferAllowed, source, reason),
                InternetManagedRestrictionResult(RESTRICTION_AUDIO, audioAllowed, source, reason),
                InternetManagedRestrictionResult(RESTRICTION_WAKE, wakeAllowed, source, reason),
                InternetManagedRestrictionResult(RESTRICTION_CUSTOM_GESTURES, customGesturesAllowed, source, reason),
                InternetManagedRestrictionResult(RESTRICTION_HOST_ACTIONS, hostActionsAllowed, source, reason),
                InternetManagedRestrictionResult(
                    RESTRICTION_MAXIMUM_FILE_BYTES,
                    maximumFileBytes > 0L,
                    source,
                    "$reason maximum_file_bytes=$maximumFileBytes.",
                ),
                InternetManagedRestrictionResult(
                    RESTRICTION_ALLOWED_HOSTS,
                    !allowedHostsRestricted || effectiveAllowedHosts.isNotEmpty(),
                    source,
                    if (allowedHostsRestricted) {
                        "$reason allowed_hosts=${effectiveAllowedHosts.sorted().joinToString(",")}."
                    } else {
                        "$reason allowed_hosts unrestricted."
                    },
                ),
                InternetManagedRestrictionResult(
                    RESTRICTION_DENIED_HOSTS,
                    deniedHosts.isEmpty(),
                    source,
                    if (deniedHosts.isEmpty()) {
                        "$reason denied_hosts empty."
                    } else {
                        "$reason denied_hosts=${deniedHosts.sorted().joinToString(",")}."
                    },
                ),
            )
        }

        private fun normalizeHost(hostId: String): String? = hostId.trim().ifEmpty { null }?.lowercase()
    }
}

internal class InternetManagedPolicyResolver(
    private val localPolicy: InternetManagedPolicy = InternetManagedPolicy.UNMANAGED,
) {
    private var remotePolicy: InternetManagedPolicy? = null

    val effectivePolicy: InternetManagedPolicy
        get() = remotePolicy?.let(localPolicy::applying) ?: localPolicy

    fun setRemote(policy: InternetManagedPolicy?) {
        remotePolicy = policy
    }

    fun clearRemote() {
        remotePolicy = null
    }
}
