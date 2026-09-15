package dev.telemachus.display

import android.content.ClipData
import android.content.Intent
import android.net.Uri

internal sealed class ShareFileIntentDecision {
    data class Accepted(
        val uri: Uri,
        val mimeType: String,
    ) : ShareFileIntentDecision()

    data class Rejected(
        val reason: ShareFileIntentRejectionReason,
    ) : ShareFileIntentDecision()
}

internal enum class ShareFileIntentRejectionReason {
    NULL_INTENT,
    UNSUPPORTED_ACTION,
    MISSING_MIME_TYPE,
    TEXT_ONLY,
    MISSING_STREAM,
    MULTIPLE_ITEMS,
    INVALID_STREAM,
    UNSUPPORTED_URI,
}

internal object ShareFileIntentPolicy {
    fun isShareCandidate(intent: Intent?): Boolean =
        intent?.action == Intent.ACTION_SEND || intent?.action == Intent.ACTION_SEND_MULTIPLE

    fun resolve(intent: Intent?): ShareFileIntentDecision {
        if (intent == null) return ShareFileIntentDecision.Rejected(ShareFileIntentRejectionReason.NULL_INTENT)
        if (intent.action != Intent.ACTION_SEND) {
            return ShareFileIntentDecision.Rejected(ShareFileIntentRejectionReason.UNSUPPORTED_ACTION)
        }

        val mimeType = intent.type?.trim().orEmpty()
        if (mimeType.isEmpty()) return ShareFileIntentDecision.Rejected(ShareFileIntentRejectionReason.MISSING_MIME_TYPE)

        val clipDecision =
            try {
                clipDataDecision(intent.clipData)
            } catch (_: RuntimeException) {
                return ShareFileIntentDecision.Rejected(ShareFileIntentRejectionReason.INVALID_STREAM)
            }
        if (clipDecision == ClipDataDecision.MultipleItems) {
            return ShareFileIntentDecision.Rejected(ShareFileIntentRejectionReason.MULTIPLE_ITEMS)
        }

        val streamDecision = streamUris(intent)
        if (streamDecision is StreamDecision.Invalid) {
            return ShareFileIntentDecision.Rejected(streamDecision.reason)
        }
        val extraStreamUri = (streamDecision as StreamDecision.Valid).uris.singleOrNull()
        val clipStreamUri = (clipDecision as? ClipDataDecision.SingleUri)?.uri
        if (extraStreamUri != null && clipStreamUri != null && extraStreamUri != clipStreamUri) {
            return ShareFileIntentDecision.Rejected(ShareFileIntentRejectionReason.MULTIPLE_ITEMS)
        }
        val streamUri = extraStreamUri ?: clipStreamUri
        if (streamUri == null) {
            return if (isTextOnlyShare(intent, mimeType)) {
                ShareFileIntentDecision.Rejected(ShareFileIntentRejectionReason.TEXT_ONLY)
            } else {
                ShareFileIntentDecision.Rejected(ShareFileIntentRejectionReason.MISSING_STREAM)
            }
        }

        if (streamUri.scheme != CONTENT_URI_SCHEME) {
            return ShareFileIntentDecision.Rejected(ShareFileIntentRejectionReason.UNSUPPORTED_URI)
        }
        return ShareFileIntentDecision.Accepted(streamUri, mimeType)
    }

    fun consumptionToken(intent: Intent): String =
        listOf(
            intent.action.orEmpty(),
            intent.type.orEmpty(),
            streamToken(intent),
            clipToken(intent),
        ).joinToString(separator = "|")

    private fun isTextOnlyShare(
        intent: Intent,
        mimeType: String,
    ): Boolean =
        mimeType.startsWith("text/", ignoreCase = true) || hasTextExtra(intent)

    private fun hasTextExtra(intent: Intent): Boolean =
        try {
            intent.hasExtra(Intent.EXTRA_TEXT) || intent.hasExtra(Intent.EXTRA_HTML_TEXT)
        } catch (_: RuntimeException) {
            false
        }

    private fun streamUris(intent: Intent): StreamDecision {
        val value =
            try {
                intent.extras?.get(Intent.EXTRA_STREAM)
            } catch (_: RuntimeException) {
                return StreamDecision.Invalid(ShareFileIntentRejectionReason.INVALID_STREAM)
            } ?: return StreamDecision.Valid(emptyList())
        val uris =
            when (value) {
                is Uri -> listOf(value)
                is ArrayList<*> -> {
                    if (value.size > 1) return StreamDecision.Invalid(ShareFileIntentRejectionReason.MULTIPLE_ITEMS)
                    val uri = value.singleOrNull() as? Uri
                        ?: return StreamDecision.Invalid(ShareFileIntentRejectionReason.INVALID_STREAM)
                    listOf(uri)
                }
                else -> return StreamDecision.Invalid(ShareFileIntentRejectionReason.INVALID_STREAM)
            }
        if (uris.size > 1) return StreamDecision.Invalid(ShareFileIntentRejectionReason.MULTIPLE_ITEMS)
        return StreamDecision.Valid(uris)
    }

    private fun clipDataDecision(clipData: ClipData?): ClipDataDecision {
        if (clipData == null || clipData.itemCount == 0) return ClipDataDecision.None
        if (clipData.itemCount > 1) return ClipDataDecision.MultipleItems
        return clipData.getItemAt(0).uri?.let(ClipDataDecision::SingleUri) ?: ClipDataDecision.None
    }

    private fun streamToken(intent: Intent): String =
        try {
            when (val value = intent.extras?.get(Intent.EXTRA_STREAM)) {
                is Uri -> value.toString()
                is ArrayList<*> -> value.joinToString(prefix = "[", postfix = "]") { it.toString() }
                null -> ""
                else -> value.javaClass.name
            }
        } catch (_: RuntimeException) {
            INVALID_TOKEN
        }

    private fun clipToken(intent: Intent): String {
        return try {
            val clipData = intent.clipData ?: return ""
            (0 until clipData.itemCount)
                .joinToString(prefix = "[", postfix = "]") { index ->
                    clipData.getItemAt(index).uri?.toString().orEmpty()
                }
        } catch (_: RuntimeException) {
            INVALID_TOKEN
        }
    }

    private sealed class StreamDecision {
        data class Valid(val uris: List<Uri>) : StreamDecision()
        data class Invalid(val reason: ShareFileIntentRejectionReason) : StreamDecision()
    }

    private sealed class ClipDataDecision {
        data object None : ClipDataDecision()
        data class SingleUri(val uri: Uri) : ClipDataDecision()
        data object MultipleItems : ClipDataDecision()
    }

    private const val CONTENT_URI_SCHEME = "content"
    private const val INVALID_TOKEN = "<invalid>"
}
