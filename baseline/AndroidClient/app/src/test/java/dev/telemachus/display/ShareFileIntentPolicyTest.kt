package dev.telemachus.display

import android.content.ClipData
import android.content.Intent
import android.net.Uri
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class ShareFileIntentPolicyTest {
    @Test
    fun acceptsSingleActionSendContentStreamWithMimeType() {
        val uri = Uri.parse("content://files/report.pdf")
        val decision = ShareFileIntentPolicy.resolve(sendIntent(uri, "application/pdf"))

        assertEquals(ShareFileIntentDecision.Accepted(uri, "application/pdf"), decision)
    }

    @Test
    fun acceptsSingleClipDataContentUriWithoutExtraStream() {
        val uri = Uri.parse("content://files/report.pdf")
        val intent =
            Intent(Intent.ACTION_SEND)
                .setType("application/pdf")
                .apply { clipData = ClipData.newRawUri("report", uri) }

        assertEquals(ShareFileIntentDecision.Accepted(uri, "application/pdf"), ShareFileIntentPolicy.resolve(intent))
    }

    @Test
    fun acceptsSingleContentUriArrayListButRejectsMultipleItems() {
        val uri = Uri.parse("content://files/report.pdf")
        val single =
            Intent(Intent.ACTION_SEND)
                .setType("application/pdf")
                .putParcelableArrayListExtra(Intent.EXTRA_STREAM, arrayListOf(uri))

        assertEquals(ShareFileIntentDecision.Accepted(uri, "application/pdf"), ShareFileIntentPolicy.resolve(single))
    }

    @Test
    fun rejectsNullUnsupportedAndMultipleActions() {
        assertRejected(null, ShareFileIntentRejectionReason.NULL_INTENT)
        assertRejected(Intent(Intent.ACTION_VIEW), ShareFileIntentRejectionReason.UNSUPPORTED_ACTION)
        assertRejected(Intent(Intent.ACTION_SEND_MULTIPLE), ShareFileIntentRejectionReason.UNSUPPORTED_ACTION)
    }

    @Test
    fun rejectsTextOnlyAndMissingStreams() {
        assertRejected(
            Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, "hello"),
            ShareFileIntentRejectionReason.TEXT_ONLY,
        )
        assertRejected(
            Intent(Intent.ACTION_SEND).setType("application/pdf"),
            ShareFileIntentRejectionReason.MISSING_STREAM,
        )
        assertRejected(
            Intent(Intent.ACTION_SEND).putExtra(Intent.EXTRA_STREAM, Uri.parse("content://files/report")),
            ShareFileIntentRejectionReason.MISSING_MIME_TYPE,
        )
    }

    @Test
    fun rejectsMultipleOrMalformedStreamItems() {
        val first = Uri.parse("content://files/first")
        val second = Uri.parse("content://files/second")
        assertRejected(
            Intent(Intent.ACTION_SEND)
                .setType("*/*")
                .putParcelableArrayListExtra(Intent.EXTRA_STREAM, arrayListOf(first, second)),
            ShareFileIntentRejectionReason.MULTIPLE_ITEMS,
        )
        assertRejected(
            Intent(Intent.ACTION_SEND).setType("*/*").putExtra(Intent.EXTRA_STREAM, "not-a-uri"),
            ShareFileIntentRejectionReason.INVALID_STREAM,
        )
    }

    @Test
    fun rejectsMultipleClipItemsAndConflictingSingleClipUri() {
        val first = Uri.parse("content://files/first")
        val second = Uri.parse("content://files/second")
        val multiple = sendIntent(first, "*/*").apply {
            clipData = ClipData.newRawUri("first", first).also { it.addItem(ClipData.Item(second)) }
        }
        assertRejected(multiple, ShareFileIntentRejectionReason.MULTIPLE_ITEMS)

        val conflicting = sendIntent(first, "*/*").apply {
            clipData = ClipData.newRawUri("second", second)
        }
        assertRejected(conflicting, ShareFileIntentRejectionReason.MULTIPLE_ITEMS)
    }

    @Test
    fun rejectsNonContentUris() {
        assertRejected(
            sendIntent(Uri.parse("file:///sdcard/Download/report.pdf"), "application/pdf"),
            ShareFileIntentRejectionReason.UNSUPPORTED_URI,
        )
        assertRejected(
            sendIntent(Uri.parse("https://example.com/report.pdf"), "application/pdf"),
            ShareFileIntentRejectionReason.UNSUPPORTED_URI,
        )
    }

    @Test
    fun consumptionTokenIsStableForEquivalentIntentAndChangesForNewStream() {
        val first = sendIntent(Uri.parse("content://files/first"), "application/pdf")
        val equivalent = sendIntent(Uri.parse("content://files/first"), "application/pdf")
        val second = sendIntent(Uri.parse("content://files/second"), "application/pdf")

        assertEquals(ShareFileIntentPolicy.consumptionToken(first), ShareFileIntentPolicy.consumptionToken(equivalent))
        assertTrue(ShareFileIntentPolicy.consumptionToken(first) != ShareFileIntentPolicy.consumptionToken(second))
    }

    private fun sendIntent(uri: Uri, mimeType: String): Intent =
        Intent(Intent.ACTION_SEND)
            .setType(mimeType)
            .putExtra(Intent.EXTRA_STREAM, uri)

    private fun assertRejected(intent: Intent?, reason: ShareFileIntentRejectionReason) {
        assertEquals(ShareFileIntentDecision.Rejected(reason), ShareFileIntentPolicy.resolve(intent))
    }
}
