package dev.telemachus.display.internet

import com.google.protobuf.ByteString
import dev.telemachus.display.ClipboardContentData
import dev.telemachus.display.ClipboardOfferData
import dev.vibescreen.protocol.v1.ClipboardContent
import dev.vibescreen.protocol.v1.ClipboardOffer
import dev.vibescreen.protocol.v1.ClipboardRequest
import dev.vibescreen.protocol.v1.ManagedPolicyStatus
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.security.SecureRandom

class InternetClipboardTest {
    private val localDeviceId = "device-android"
    private val remoteDeviceId = "device-host"

    private fun clipboard(maximumBytes: Long = 1024L): InternetClipboard =
        InternetClipboard(
            localDeviceId = localDeviceId,
            remoteDeviceId = remoteDeviceId,
            maximumBytes = maximumBytes,
            random = SecureRandom(byteArrayOf(1, 2, 3, 4, 5, 6, 7, 8)),
        )

    private fun changeId(seed: Int = 0x11): ByteString =
        ByteString.copyFrom(ByteArray(InternetClipboard.CLIPBOARD_CHANGE_ID_BYTES) { seed.toByte() })

    private fun sha256(bytes: ByteArray): ByteString =
        ByteString.copyFrom(InternetClipboard.sha256(bytes))

    @Test
    fun constructorRejectsBlankIdentities() {
        assertThrows(IllegalArgumentException::class.java) {
            InternetClipboard("", remoteDeviceId, 1024L)
        }
        assertThrows(IllegalArgumentException::class.java) {
            InternetClipboard(localDeviceId, "  ", 1024L)
        }
    }

    @Test
    fun constructorRejectsInvalidByteLimit() {
        assertThrows(IllegalArgumentException::class.java) {
            InternetClipboard(localDeviceId, remoteDeviceId, 0L)
        }
        assertThrows(IllegalArgumentException::class.java) {
            InternetClipboard(localDeviceId, remoteDeviceId, InternetClipboard.LOCAL_MAX_CLIPBOARD_BYTES + 1L)
        }
    }

    @Test
    fun prepareOfferReturnsNullForEmptyOrOversizeText() {
        val cb = clipboard(maximumBytes = 8L)
        assertNull(cb.prepareOffer(""))
        assertNull(cb.prepareOffer("123456789"))
    }

    @Test
    fun prepareOfferBuildsOfferAndStoresSnapshot() {
        val cb = clipboard()
        val offer = cb.prepareOffer("hello")
        assertNotNull(offer)
        assertEquals(localDeviceId, offer!!.originDeviceId)
        assertEquals(InternetClipboard.CLIPBOARD_MIME_TEXT_PLAIN, offer.mimeType)
        assertEquals("hello".toByteArray(Charsets.UTF_8).size.toLong(), offer.byteLength)
        assertEquals(InternetClipboard.CLIPBOARD_CHANGE_ID_BYTES, offer.changeId.size())
        assertEquals(InternetClipboard.CLIPBOARD_SHA256_BYTES, offer.sha256.size())
        assertArrayEquals(
            InternetClipboard.sha256("hello".toByteArray(Charsets.UTF_8)),
            offer.sha256.toByteArray(),
        )
    }

    @Test
    fun makeContentReturnsContentForMatchingChangeId() {
        val cb = clipboard()
        val offer = cb.prepareOffer("hello")!!
        val content = cb.makeContent(ClipboardRequest.newBuilder().setChangeId(offer.changeId).build())
        assertNotNull(content)
        assertEquals(offer.changeId, content!!.changeId)
        assertEquals(localDeviceId, content.originDeviceId)
        assertEquals(InternetClipboard.CLIPBOARD_MIME_TEXT_PLAIN, content.mimeType)
        assertArrayEquals("hello".toByteArray(Charsets.UTF_8), content.content.toByteArray())
        assertArrayEquals(offer.sha256.toByteArray(), content.sha256.toByteArray())
    }

    @Test
    fun makeContentRejectsInvalidChangeIdLength() {
        val cb = clipboard()
        cb.prepareOffer("hello")
        assertThrows(IllegalArgumentException::class.java) {
            cb.makeContent(ClipboardRequest.newBuilder().setChangeId(ByteString.copyFrom(byteArrayOf(1, 2, 3))).build())
        }
    }

    @Test
    fun makeContentReturnsNullForUnknownOrConsumedChangeId() {
        val cb = clipboard()
        val offer = cb.prepareOffer("hello")!!
        val other = changeId(0x22)
        assertNull(cb.makeContent(ClipboardRequest.newBuilder().setChangeId(other).build()))

        val content = cb.makeContent(ClipboardRequest.newBuilder().setChangeId(offer.changeId).build())
        assertNotNull(content)
        assertNull(cb.makeContent(ClipboardRequest.newBuilder().setChangeId(offer.changeId).build()))
    }

    @Test
    fun handleOfferStoresPendingOfferAndClearsRequest() {
        val cb = clipboard()
        val text = "from host".toByteArray(Charsets.UTF_8)
        val id = changeId(0x33)
        val offer = ClipboardOffer.newBuilder()
            .setChangeId(id)
            .setOriginDeviceId(remoteDeviceId)
            .setMimeType(InternetClipboard.CLIPBOARD_MIME_TEXT_PLAIN)
            .setByteLength(text.size.toLong())
            .setSha256(sha256(text))
            .build()

        val data = cb.handleOffer(offer)
        assertArrayEquals(id.toByteArray(), data.changeId)
        assertEquals(remoteDeviceId, data.originDeviceId)
        assertEquals(InternetClipboard.CLIPBOARD_MIME_TEXT_PLAIN, data.mimeType)
        assertEquals(text.size.toLong(), data.byteLength)
        assertArrayEquals(sha256(text).toByteArray(), data.sha256)
    }

    @Test
    fun handleOfferRejectsWrongOriginDeviceId() {
        val cb = clipboard()
        val text = "x".toByteArray(Charsets.UTF_8)
        val offer = ClipboardOffer.newBuilder()
            .setChangeId(changeId())
            .setOriginDeviceId("other-host")
            .setMimeType(InternetClipboard.CLIPBOARD_MIME_TEXT_PLAIN)
            .setByteLength(text.size.toLong())
            .setSha256(sha256(text))
            .build()
        assertThrows(IllegalArgumentException::class.java) { cb.handleOffer(offer) }
    }

    @Test
    fun handleOfferRejectsInvalidChangeIdLength() {
        val cb = clipboard()
        val text = "x".toByteArray(Charsets.UTF_8)
        val offer = ClipboardOffer.newBuilder()
            .setChangeId(ByteString.copyFrom(byteArrayOf(1, 2, 3)))
            .setOriginDeviceId(remoteDeviceId)
            .setMimeType(InternetClipboard.CLIPBOARD_MIME_TEXT_PLAIN)
            .setByteLength(text.size.toLong())
            .setSha256(sha256(text))
            .build()
        assertThrows(IllegalArgumentException::class.java) { cb.handleOffer(offer) }
    }

    @Test
    fun handleOfferRejectsWrongMimeType() {
        val cb = clipboard()
        val text = "x".toByteArray(Charsets.UTF_8)
        val offer = ClipboardOffer.newBuilder()
            .setChangeId(changeId())
            .setOriginDeviceId(remoteDeviceId)
            .setMimeType("application/octet-stream")
            .setByteLength(text.size.toLong())
            .setSha256(sha256(text))
            .build()
        assertThrows(IllegalArgumentException::class.java) { cb.handleOffer(offer) }
    }

    @Test
    fun handleOfferRejectsInvalidByteLength() {
        val cb = clipboard(maximumBytes = 4L)
        val text = "x".toByteArray(Charsets.UTF_8)
        val offer = ClipboardOffer.newBuilder()
            .setChangeId(changeId())
            .setOriginDeviceId(remoteDeviceId)
            .setMimeType(InternetClipboard.CLIPBOARD_MIME_TEXT_PLAIN)
            .setByteLength(0L)
            .setSha256(sha256(text))
            .build()
        assertThrows(IllegalArgumentException::class.java) { cb.handleOffer(offer) }

        val oversize = ClipboardOffer.newBuilder()
            .setChangeId(changeId(0x44))
            .setOriginDeviceId(remoteDeviceId)
            .setMimeType(InternetClipboard.CLIPBOARD_MIME_TEXT_PLAIN)
            .setByteLength(5L)
            .setSha256(sha256(text))
            .build()
        assertThrows(IllegalArgumentException::class.java) { cb.handleOffer(oversize) }
    }

    @Test
    fun handleOfferRejectsInvalidSha256Length() {
        val cb = clipboard()
        val text = "x".toByteArray(Charsets.UTF_8)
        val offer = ClipboardOffer.newBuilder()
            .setChangeId(changeId())
            .setOriginDeviceId(remoteDeviceId)
            .setMimeType(InternetClipboard.CLIPBOARD_MIME_TEXT_PLAIN)
            .setByteLength(text.size.toLong())
            .setSha256(ByteString.copyFrom(byteArrayOf(1, 2, 3)))
            .build()
        assertThrows(IllegalArgumentException::class.java) { cb.handleOffer(offer) }
    }

    @Test
    fun handleOfferRejectsLoopbackChangeId() {
        val cb = clipboard()
        val offer = cb.prepareOffer("local")!!
        val remote = ClipboardOffer.newBuilder()
            .setChangeId(offer.changeId)
            .setOriginDeviceId(remoteDeviceId)
            .setMimeType(InternetClipboard.CLIPBOARD_MIME_TEXT_PLAIN)
            .setByteLength(1L)
            .setSha256(sha256("x".toByteArray(Charsets.UTF_8)))
            .build()
        assertThrows(IllegalArgumentException::class.java) { cb.handleOffer(remote) }
    }

    @Test
    fun handleOfferAcceptsRepeatedOfferWithIdenticalMetadata() {
        val cb = clipboard()
        val text = "x".toByteArray(Charsets.UTF_8)
        val id = changeId(0x55)
        val offer = ClipboardOffer.newBuilder()
            .setChangeId(id)
            .setOriginDeviceId(remoteDeviceId)
            .setMimeType(InternetClipboard.CLIPBOARD_MIME_TEXT_PLAIN)
            .setByteLength(text.size.toLong())
            .setSha256(sha256(text))
            .build()
        val first = cb.handleOffer(offer)
        val second = cb.handleOffer(offer)
        assertArrayEquals(first.changeId, second.changeId)
        assertEquals(first.byteLength, second.byteLength)
    }

    @Test
    fun handleOfferRejectsMetadataChangeForSameChangeId() {
        val cb = clipboard()
        val text = "x".toByteArray(Charsets.UTF_8)
        val id = changeId(0x66)
        val offer = ClipboardOffer.newBuilder()
            .setChangeId(id)
            .setOriginDeviceId(remoteDeviceId)
            .setMimeType(InternetClipboard.CLIPBOARD_MIME_TEXT_PLAIN)
            .setByteLength(text.size.toLong())
            .setSha256(sha256(text))
            .build()
        cb.handleOffer(offer)
        val modified = offer.toBuilder().setByteLength(text.size.toLong() + 1L).build()
        assertThrows(IllegalArgumentException::class.java) { cb.handleOffer(modified) }
    }

    @Test
    fun requestContentReturnsNullWithoutPendingOffer() {
        val cb = clipboard()
        assertNull(cb.requestContent(changeId().toByteArray()))
    }

    @Test
    fun requestContentReturnsRequestForMatchingOffer() {
        val cb = clipboard()
        val text = "x".toByteArray(Charsets.UTF_8)
        val id = changeId(0x77)
        cb.handleOffer(ClipboardOffer.newBuilder()
            .setChangeId(id)
            .setOriginDeviceId(remoteDeviceId)
            .setMimeType(InternetClipboard.CLIPBOARD_MIME_TEXT_PLAIN)
            .setByteLength(text.size.toLong())
            .setSha256(sha256(text))
            .build())
        val request = cb.requestContent(id.toByteArray())
        assertNotNull(request)
        assertEquals(id, request!!.changeId)
    }

    @Test
    fun requestContentRejectsMismatchedOrDuplicateChangeId() {
        val cb = clipboard()
        val text = "x".toByteArray(Charsets.UTF_8)
        val id = changeId(0x88)
        cb.handleOffer(ClipboardOffer.newBuilder()
            .setChangeId(id)
            .setOriginDeviceId(remoteDeviceId)
            .setMimeType(InternetClipboard.CLIPBOARD_MIME_TEXT_PLAIN)
            .setByteLength(text.size.toLong())
            .setSha256(sha256(text))
            .build())
        assertNull(cb.requestContent(changeId(0x99).toByteArray()))
        assertNotNull(cb.requestContent(id.toByteArray()))
        assertNull(cb.requestContent(id.toByteArray()))
    }

    @Test
    fun expireRequestClearsPendingRequest() {
        val cb = clipboard()
        val text = "x".toByteArray(Charsets.UTF_8)
        val id = changeId(0xaa)
        cb.handleOffer(ClipboardOffer.newBuilder()
            .setChangeId(id)
            .setOriginDeviceId(remoteDeviceId)
            .setMimeType(InternetClipboard.CLIPBOARD_MIME_TEXT_PLAIN)
            .setByteLength(text.size.toLong())
            .setSha256(sha256(text))
            .build())
        cb.requestContent(id.toByteArray())
        assertFalse(cb.expireRequest(changeId(0xbb).toByteArray()))
        assertTrue(cb.expireRequest(id.toByteArray()))
        assertFalse(cb.expireRequest(id.toByteArray()))
    }

    @Test
    fun handleContentSolicitedReturnsNonPendingAndConsumesOffer() {
        val cb = clipboard()
        val text = "from host".toByteArray(Charsets.UTF_8)
        val id = changeId(0xcc)
        val offer = ClipboardOffer.newBuilder()
            .setChangeId(id)
            .setOriginDeviceId(remoteDeviceId)
            .setMimeType(InternetClipboard.CLIPBOARD_MIME_TEXT_PLAIN)
            .setByteLength(text.size.toLong())
            .setSha256(sha256(text))
            .build()
        cb.handleOffer(offer)
        cb.requestContent(id.toByteArray())
        val content = ClipboardContent.newBuilder()
            .setChangeId(id)
            .setOriginDeviceId(remoteDeviceId)
            .setMimeType(InternetClipboard.CLIPBOARD_MIME_TEXT_PLAIN)
            .setContent(ByteString.copyFrom(text))
            .setSha256(sha256(text))
            .build()
        val data = cb.handleContent(content)
        assertFalse(data.pending)
        assertArrayEquals(text, data.content)
        assertArrayEquals(id.toByteArray(), data.changeId)
    }

    @Test
    fun handleContentDirectReturnsPending() {
        val cb = clipboard()
        val text = "direct".toByteArray(Charsets.UTF_8)
        val id = changeId(0xdd)
        val content = ClipboardContent.newBuilder()
            .setChangeId(id)
            .setOriginDeviceId(remoteDeviceId)
            .setMimeType(InternetClipboard.CLIPBOARD_MIME_TEXT_PLAIN)
            .setContent(ByteString.copyFrom(text))
            .setSha256(sha256(text))
            .build()
        val data = cb.handleContent(content)
        assertTrue(data.pending)
        assertArrayEquals(text, data.content)
    }

    @Test
    fun handleContentRejectsInvalidDigest() {
        val cb = clipboard()
        val text = "x".toByteArray(Charsets.UTF_8)
        val id = changeId(0xee)
        val content = ClipboardContent.newBuilder()
            .setChangeId(id)
            .setOriginDeviceId(remoteDeviceId)
            .setMimeType(InternetClipboard.CLIPBOARD_MIME_TEXT_PLAIN)
            .setContent(ByteString.copyFrom(text))
            .setSha256(ByteString.copyFrom(ByteArray(InternetClipboard.CLIPBOARD_SHA256_BYTES) { 0x7f }))
            .build()
        assertThrows(IllegalArgumentException::class.java) { cb.handleContent(content) }
    }

    @Test
    fun handleContentRejectsInvalidChangeIdLength() {
        val cb = clipboard()
        val text = "x".toByteArray(Charsets.UTF_8)
        val content = ClipboardContent.newBuilder()
            .setChangeId(ByteString.copyFrom(byteArrayOf(1, 2, 3)))
            .setOriginDeviceId(remoteDeviceId)
            .setMimeType(InternetClipboard.CLIPBOARD_MIME_TEXT_PLAIN)
            .setContent(ByteString.copyFrom(text))
            .setSha256(sha256(text))
            .build()
        assertThrows(IllegalArgumentException::class.java) { cb.handleContent(content) }
    }

    @Test
    fun handleContentRejectsWrongMime() {
        val cb = clipboard()
        val text = "x".toByteArray(Charsets.UTF_8)
        val id = changeId(0xff)
        val content = ClipboardContent.newBuilder()
            .setChangeId(id)
            .setOriginDeviceId(remoteDeviceId)
            .setMimeType("text/html")
            .setContent(ByteString.copyFrom(text))
            .setSha256(sha256(text))
            .build()
        assertThrows(IllegalArgumentException::class.java) { cb.handleContent(content) }
    }

    @Test
    fun handleContentRejectsOversize() {
        val cb = clipboard(maximumBytes = 4L)
        val text = "12345".toByteArray(Charsets.UTF_8)
        val id = changeId(0x01)
        val content = ClipboardContent.newBuilder()
            .setChangeId(id)
            .setOriginDeviceId(remoteDeviceId)
            .setMimeType(InternetClipboard.CLIPBOARD_MIME_TEXT_PLAIN)
            .setContent(ByteString.copyFrom(text))
            .setSha256(sha256(text))
            .build()
        assertThrows(IllegalArgumentException::class.java) { cb.handleContent(content) }
    }

    @Test
    fun handleContentRejectsInvalidUtf8() {
        val cb = clipboard()
        val bytes = byteArrayOf(0xc3.toByte(), 0x28)
        val id = changeId(0x02)
        val content = ClipboardContent.newBuilder()
            .setChangeId(id)
            .setOriginDeviceId(remoteDeviceId)
            .setMimeType(InternetClipboard.CLIPBOARD_MIME_TEXT_PLAIN)
            .setContent(ByteString.copyFrom(bytes))
            .setSha256(sha256(bytes))
            .build()
        assertThrows(IllegalArgumentException::class.java) { cb.handleContent(content) }
    }

    @Test
    fun handleContentRejectsLoopbackChangeId() {
        val cb = clipboard()
        val offer = cb.prepareOffer("local")!!
        val text = "x".toByteArray(Charsets.UTF_8)
        val content = ClipboardContent.newBuilder()
            .setChangeId(offer.changeId)
            .setOriginDeviceId(remoteDeviceId)
            .setMimeType(InternetClipboard.CLIPBOARD_MIME_TEXT_PLAIN)
            .setContent(ByteString.copyFrom(text))
            .setSha256(sha256(text))
            .build()
        assertThrows(IllegalArgumentException::class.java) { cb.handleContent(content) }
    }

    @Test
    fun handleContentSolicitedRejectsOfferMismatch() {
        val cb = clipboard()
        val text = "x".toByteArray(Charsets.UTF_8)
        val id = changeId(0x03)
        val offer = ClipboardOffer.newBuilder()
            .setChangeId(id)
            .setOriginDeviceId(remoteDeviceId)
            .setMimeType(InternetClipboard.CLIPBOARD_MIME_TEXT_PLAIN)
            .setByteLength(text.size.toLong())
            .setSha256(sha256(text))
            .build()
        cb.handleOffer(offer)
        cb.requestContent(id.toByteArray())
        val wrongLength = ClipboardContent.newBuilder()
            .setChangeId(id)
            .setOriginDeviceId(remoteDeviceId)
            .setMimeType(InternetClipboard.CLIPBOARD_MIME_TEXT_PLAIN)
            .setContent(ByteString.copyFrom("xx".toByteArray(Charsets.UTF_8)))
            .setSha256(sha256("xx".toByteArray(Charsets.UTF_8)))
            .build()
        assertThrows(IllegalArgumentException::class.java) { cb.handleContent(wrongLength) }
    }

    @Test
    fun resetClearsAllState() {
        val cb = clipboard()
        cb.prepareOffer("local")
        val text = "x".toByteArray(Charsets.UTF_8)
        val id = changeId(0x04)
        cb.handleOffer(ClipboardOffer.newBuilder()
            .setChangeId(id)
            .setOriginDeviceId(remoteDeviceId)
            .setMimeType(InternetClipboard.CLIPBOARD_MIME_TEXT_PLAIN)
            .setByteLength(text.size.toLong())
            .setSha256(sha256(text))
            .build())
        cb.reset()
        assertNull(cb.requestContent(id.toByteArray()))
        val offer = cb.prepareOffer("after reset")
        assertNotNull(offer)
    }

    @Test
    fun seenChangeIdsPreventsReplayAfterSolicitedContent() {
        val cb = clipboard()
        val text = "x".toByteArray(Charsets.UTF_8)
        val id = changeId(0x05)
        cb.handleOffer(ClipboardOffer.newBuilder()
            .setChangeId(id)
            .setOriginDeviceId(remoteDeviceId)
            .setMimeType(InternetClipboard.CLIPBOARD_MIME_TEXT_PLAIN)
            .setByteLength(text.size.toLong())
            .setSha256(sha256(text))
            .build())
        cb.requestContent(id.toByteArray())
        cb.handleContent(ClipboardContent.newBuilder()
            .setChangeId(id)
            .setOriginDeviceId(remoteDeviceId)
            .setMimeType(InternetClipboard.CLIPBOARD_MIME_TEXT_PLAIN)
            .setContent(ByteString.copyFrom(text))
            .setSha256(sha256(text))
            .build())
        assertThrows(IllegalArgumentException::class.java) {
            cb.handleOffer(ClipboardOffer.newBuilder()
                .setChangeId(id)
                .setOriginDeviceId(remoteDeviceId)
                .setMimeType(InternetClipboard.CLIPBOARD_MIME_TEXT_PLAIN)
                .setByteLength(text.size.toLong())
                .setSha256(sha256(text))
                .build())
        }
    }
}

class InternetManagedPolicyTest {
    @Test
    fun unmanagedPolicyAllowsEverything() {
        val policy = InternetManagedPolicy.UNMANAGED
        assertFalse(policy.isManaged)
        assertTrue(policy.clipboardAllowed)
        assertTrue(policy.effectiveFileTransferAllowed)
        assertFalse(policy.effectiveAllowedHostsRestricted)
        assertTrue(policy.allowsHost("any-host"))
    }

    @Test
    fun allowsHostRespectsDeniedHosts() {
        val policy = InternetManagedPolicy.UNMANAGED.copy(
            isManaged = true,
            deniedHosts = setOf("bad-host"),
        )
        assertFalse(policy.allowsHost("bad-host"))
        assertTrue(policy.allowsHost("good-host"))
    }

    @Test
    fun allowsHostRespectsAllowedHostsRestriction() {
        val policy = InternetManagedPolicy.UNMANAGED.copy(
            isManaged = true,
            allowedHosts = setOf("good-host"),
            allowedHostsRestricted = true,
        )
        assertTrue(policy.allowsHost("good-host"))
        assertFalse(policy.allowsHost("other-host"))
    }

    @Test
    fun allowsHostNormalizesHostIds() {
        val policy = InternetManagedPolicy.UNMANAGED.copy(
            isManaged = true,
            allowedHosts = setOf("Good-Host "),
            allowedHostsRestricted = true,
            deniedHosts = setOf(" Bad-Host"),
        )
        assertTrue(policy.allowsHost("good-host"))
        assertFalse(policy.allowsHost("bad-host"))
    }

    @Test
    fun applyingUsesDenyWinsSemantics() {
        val local = InternetManagedPolicy.UNMANAGED.copy(
            isManaged = true,
            clipboardAllowed = true,
            fileTransferAllowed = true,
            maximumFileBytes = 1024L,
            allowedHosts = setOf("a", "b"),
            allowedHostsRestricted = true,
        )
        val remote = InternetManagedPolicy.UNMANAGED.copy(
            isManaged = true,
            clipboardAllowed = false,
            fileTransferAllowed = true,
            maximumFileBytes = 512L,
            allowedHosts = setOf("b", "c"),
            allowedHostsRestricted = true,
        )
        val effective = local.applying(remote)
        assertFalse(effective.clipboardAllowed)
        assertEquals(512L, effective.maximumFileBytes)
        assertTrue(effective.allowsHost("b"))
        assertFalse(effective.allowsHost("a"))
        assertFalse(effective.allowsHost("c"))
    }

    @Test
    fun applyingIgnoresUnmanagedRemote() {
        val local = InternetManagedPolicy.UNMANAGED.copy(
            isManaged = true,
            clipboardAllowed = false,
        )
        val remote = InternetManagedPolicy.UNMANAGED
        val effective = local.applying(remote)
        assertFalse(effective.clipboardAllowed)
    }

    @Test
    fun statusRoundtripPreservesManagedPolicy() {
        val policy = InternetManagedPolicy.UNMANAGED.copy(
            isManaged = true,
            clipboardAllowed = false,
            fileTransferAllowed = true,
            audioAllowed = false,
            wakeAllowed = true,
            customGesturesAllowed = false,
            hostActionsAllowed = true,
            maximumFileBytes = 2048L,
            allowedHosts = setOf("host-1", "host-2"),
            allowedHostsRestricted = true,
            deniedHosts = setOf("host-3"),
        )
        val status = policy.toStatus()
        assertTrue(InternetManagedPolicy.hasCompleteRestrictionResults(status))
        val restored = InternetManagedPolicy.fromStatus(status)
        assertTrue(restored.isManaged)
        assertFalse(restored.clipboardAllowed)
        assertTrue(restored.fileTransferAllowed)
        assertFalse(restored.audioAllowed)
        assertEquals(2048L, restored.maximumFileBytes)
        assertEquals(setOf("host-1", "host-2"), restored.allowedHosts)
        assertTrue(restored.allowedHostsRestricted)
        assertEquals(setOf("host-3"), restored.deniedHosts)
    }

    @Test
    fun unmanagedStatusRoundtripReturnsUnmanaged() {
        val status = InternetManagedPolicy.UNMANAGED.toStatus()
        assertFalse(status.managed)
        val restored = InternetManagedPolicy.fromStatus(status)
        assertFalse(restored.isManaged)
    }

    @Test
    fun hasCompleteRestrictionResultsRejectsIncompleteResults() {
        val status = InternetManagedPolicy.UNMANAGED.copy(
            isManaged = true,
            clipboardAllowed = false,
        ).toStatus().toBuilder()
            .clearRestrictionResults()
            .build()
        assertFalse(InternetManagedPolicy.hasCompleteRestrictionResults(status))
    }

    @Test
    fun hasCompleteRestrictionResultsRejectsInconsistentAllowedFlag() {
        val status = InternetManagedPolicy.UNMANAGED.copy(
            isManaged = true,
            clipboardAllowed = false,
        ).toStatus()
        val first = status.restrictionResultsList.first()
        val tampered = status.toBuilder()
            .clearRestrictionResults()
            .addAllRestrictionResults(
                status.restrictionResultsList.map { result ->
                    if (result.restriction == first.restriction) {
                        result.toBuilder().setAllowed(!result.allowed).build()
                    } else {
                        result
                    }
                },
            )
            .build()
        assertFalse(InternetManagedPolicy.hasCompleteRestrictionResults(tampered))
    }

    @Test
    fun effectiveFileTransferAllowedRequiresPositiveMaximumBytes() {
        val policy = InternetManagedPolicy.UNMANAGED.copy(
            isManaged = true,
            fileTransferAllowed = true,
            maximumFileBytes = 0L,
        )
        assertFalse(policy.effectiveFileTransferAllowed)
    }

    @Test
    fun effectiveAllowedHostsRestrictedIsTrueWhenAllowedHostsPresent() {
        val policy = InternetManagedPolicy.UNMANAGED.copy(
            isManaged = true,
            allowedHosts = setOf("host-1"),
            allowedHostsRestricted = false,
        )
        assertTrue(policy.effectiveAllowedHostsRestricted)
    }
}

class InternetManagedPolicyResolverTest {
    @Test
    fun effectivePolicyDefaultsToLocalWhenNoRemote() {
        val local = InternetManagedPolicy.UNMANAGED.copy(
            isManaged = true,
            clipboardAllowed = false,
        )
        val resolver = InternetManagedPolicyResolver(local)
        assertEquals(local.clipboardAllowed, resolver.effectivePolicy.clipboardAllowed)
    }

    @Test
    fun effectivePolicyCombinesLocalAndRemoteWithDenyWins() {
        val local = InternetManagedPolicy.UNMANAGED.copy(
            isManaged = true,
            clipboardAllowed = true,
            maximumFileBytes = 1024L,
        )
        val remote = InternetManagedPolicy.UNMANAGED.copy(
            isManaged = true,
            clipboardAllowed = false,
            maximumFileBytes = 512L,
        )
        val resolver = InternetManagedPolicyResolver(local)
        resolver.setRemote(remote)
        val effective = resolver.effectivePolicy
        assertFalse(effective.clipboardAllowed)
        assertEquals(512L, effective.maximumFileBytes)
    }

    @Test
    fun clearRemoteRestoresLocalPolicy() {
        val local = InternetManagedPolicy.UNMANAGED.copy(
            isManaged = true,
            clipboardAllowed = true,
        )
        val remote = InternetManagedPolicy.UNMANAGED.copy(
            isManaged = true,
            clipboardAllowed = false,
        )
        val resolver = InternetManagedPolicyResolver(local)
        resolver.setRemote(remote)
        assertFalse(resolver.effectivePolicy.clipboardAllowed)
        resolver.clearRemote()
        assertTrue(resolver.effectivePolicy.clipboardAllowed)
    }

    @Test
    fun setRemoteNullClearsRemotePolicy() {
        val local = InternetManagedPolicy.UNMANAGED.copy(
            isManaged = true,
            clipboardAllowed = true,
        )
        val resolver = InternetManagedPolicyResolver(local)
        resolver.setRemote(InternetManagedPolicy.UNMANAGED.copy(isManaged = true, clipboardAllowed = false))
        resolver.setRemote(null)
        assertTrue(resolver.effectivePolicy.clipboardAllowed)
    }
}
