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
        if (intent.action != Intent.ACTION_SEND && intent.action != Intent.ACTION_SEND_MULTIPLE) {
            return ShareFileIntentDecision.Rejected(ShareFileIntentRejectionReason.UNSUPPORTED_ACTION)
        }

        val mimeType = intent.type?.trim().orEmpty()
        if (mimeType.isEmpty()) return ShareFileIntentDecision.Rejected(ShareFileIntentRejectionReason.MISSING_MIME_TYPE)

        val clipDecision = clipDataUris(intent.clipData)
        if (clipDecision is StreamDecision.Invalid) {
            return ShareFileIntentDecision.Rejected(clipDecision.reason)
        }
        val streamDecision = streamUris(intent)
        if (streamDecision is StreamDecision.Invalid) {
            return ShareFileIntentDecision.Rejected(streamDecision.reason)
        }
        val streamUris = (streamDecision as StreamDecision.Valid).uris
        if (intent.action == Intent.ACTION_SEND_MULTIPLE && streamUris.isEmpty()) {
            return if (isTextOnlyShare(intent, mimeType)) {
                ShareFileIntentDecision.Rejected(ShareFileIntentRejectionReason.TEXT_ONLY)
            } else {
                ShareFileIntentDecision.Rejected(ShareFileIntentRejectionReason.MISSING_STREAM)
            }
        }
        val clipUris = (clipDecision as StreamDecision.Valid).uris
        val distinctUris = (streamUris + clipUris).distinct()
        if (distinctUris.size > 1) {
            return ShareFileIntentDecision.Rejected(ShareFileIntentRejectionReason.MULTIPLE_ITEMS)
        }
        val streamUri = distinctUris.singleOrNull()
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
                is Uri -> {
                    if (intent.action == Intent.ACTION_SEND_MULTIPLE) {
                        return StreamDecision.Invalid(ShareFileIntentRejectionReason.INVALID_STREAM)
                    }
                    listOf(value)
                }
                is ArrayList<*> -> {
                    if (value.size > 1) return StreamDecision.Invalid(ShareFileIntentRejectionReason.MULTIPLE_ITEMS)
                    if (value.isEmpty()) {
                        emptyList()
                    } else {
                        val uri = value.singleOrNull() as? Uri
                            ?: return StreamDecision.Invalid(ShareFileIntentRejectionReason.INVALID_STREAM)
                        listOf(uri)
                    }
                }
                else -> return StreamDecision.Invalid(ShareFileIntentRejectionReason.INVALID_STREAM)
            }
        if (uris.size > 1) return StreamDecision.Invalid(ShareFileIntentRejectionReason.MULTIPLE_ITEMS)
        return StreamDecision.Valid(uris)
    }

    private fun clipDataUris(clipData: ClipData?): StreamDecision {
        if (clipData == null || clipData.itemCount == 0) return StreamDecision.Valid(emptyList())
        if (clipData.itemCount > 1) {
            return StreamDecision.Invalid(ShareFileIntentRejectionReason.MULTIPLE_ITEMS)
        }
        val uris = mutableListOf<Uri>()
        return try {
            for (index in 0 until clipData.itemCount) {
                clipData.getItemAt(index).uri?.let(uris::add)
            }
            if (uris.distinct().size > 1) {
                StreamDecision.Invalid(ShareFileIntentRejectionReason.MULTIPLE_ITEMS)
            } else {
                StreamDecision.Valid(uris.distinct())
            }
        } catch (_: RuntimeException) {
            StreamDecision.Invalid(ShareFileIntentRejectionReason.INVALID_STREAM)
        }
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

    private const val CONTENT_URI_SCHEME = "content"
    private const val INVALID_TOKEN = "<invalid>"
}
