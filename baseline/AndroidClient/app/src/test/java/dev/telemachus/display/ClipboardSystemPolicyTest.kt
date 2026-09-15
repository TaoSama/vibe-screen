package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ClipboardSystemPolicyTest {
    @Test
    fun androidSystemClipboardCapIsBelowProtocolWireCap() {
        assertEquals(1024L * 1024L, ClipboardMenuPolicy.DEFAULT_CLIPBOARD_BYTES)
        assertEquals(320L * 1024L, ClipboardSystemPolicy.ANDROID_SYSTEM_CLIPBOARD_BYTES)
        assertTrue(ClipboardSystemPolicy.ANDROID_SYSTEM_CLIPBOARD_BYTES < ClipboardMenuPolicy.DEFAULT_CLIPBOARD_BYTES)
    }

    @Test
    fun androidSystemWriteCapAcceptsZeroThroughCapOnly() {
        assertTrue(ClipboardSystemPolicy.canWriteAndroidSystemClipboard(0L))
        assertFalse(ClipboardSystemPolicy.canWriteAndroidSystemClipboard(-1L))
        assertTrue(ClipboardSystemPolicy.canWriteAndroidSystemClipboard(320L * 1024L))
        assertFalse(ClipboardSystemPolicy.canWriteAndroidSystemClipboard(320L * 1024L + 1L))
    }

    @Test
    fun remoteClipboardRequestsUseAndroidSystemWriteCap() {
        assertFalse(ClipboardSystemPolicy.canRequestRemoteClipboard(offer(byteLength = 0L)))
        assertFalse(ClipboardSystemPolicy.canRequestRemoteClipboard(offer(byteLength = -1L)))
        assertTrue(ClipboardSystemPolicy.canRequestRemoteClipboard(offer(byteLength = 320L * 1024L)))
        assertFalse(ClipboardSystemPolicy.canRequestRemoteClipboard(offer(byteLength = 320L * 1024L + 1L)))
        assertFalse(ClipboardSystemPolicy.canRequestRemoteClipboard(offer(byteLength = 512L * 1024L)))
        assertFalse(ClipboardSystemPolicy.canRequestRemoteClipboard(offer(byteLength = 1024L * 1024L)))
        assertFalse(ClipboardSystemPolicy.canRequestRemoteClipboard(null))
    }

    @Test
    fun androidSystemWriteCapIsBasedOnUtf8Bytes() {
        assertTrue(ClipboardSystemPolicy.isWithinAndroidSystemClipboardLimit(""))
        assertTrue(ClipboardSystemPolicy.isWithinAndroidSystemClipboardLimit("x".repeat(320 * 1024)))
        assertFalse(ClipboardSystemPolicy.isWithinAndroidSystemClipboardLimit("x".repeat(320 * 1024 + 1)))

        val fourByteCodePoint = "\uD83D\uDE80"
        assertTrue(ClipboardSystemPolicy.isWithinAndroidSystemClipboardLimit(fourByteCodePoint.repeat((320 * 1024) / 4)))
        assertFalse(ClipboardSystemPolicy.isWithinAndroidSystemClipboardLimit(fourByteCodePoint.repeat((320 * 1024) / 4 + 1)))
    }

    @Test
    fun sendingLocalClipboardKeepsNegotiatedProtocolCapacity() {
        val oneMiB = "x".repeat(1024 * 1024)
        val beyondOneMiB = oneMiB + "x"

        assertTrue(ClipboardMenuPolicy.isWithinSizeLimit(oneMiB, ClipboardMenuPolicy.DEFAULT_CLIPBOARD_BYTES))
        assertFalse(ClipboardMenuPolicy.isWithinSizeLimit(beyondOneMiB, ClipboardMenuPolicy.DEFAULT_CLIPBOARD_BYTES))
    }

    private fun offer(byteLength: Long): PendingClipboardOffer =
        PendingClipboardOffer(
            changeId = ByteArray(16) { 1 },
            originDeviceId = "mac",
            mimeType = "text/plain",
            byteLength = byteLength,
            sha256 = ByteArray(32) { 2 },
        )
}
