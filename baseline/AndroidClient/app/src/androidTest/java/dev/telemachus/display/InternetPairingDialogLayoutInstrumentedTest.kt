package dev.telemachus.display

import android.content.Context
import android.content.res.Configuration
import android.graphics.Bitmap
import android.graphics.Canvas
import android.text.InputType
import android.view.inputmethod.EditorInfo
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.appcompat.view.ContextThemeWrapper
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.io.FileOutputStream
import kotlin.math.roundToInt
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class InternetPairingDialogLayoutInstrumentedTest {
    @Test
    fun narrowPhoneKeepsPairingDialogContentReadableAndScrollable() {
        listOf(320 to 640, 360 to 740).forEach { (widthDp, heightDp) ->
            withPairingLayout(widthDp, heightDp, fontScale = 1.3f) { layout ->
                layout.renderSamplePayloads()
                layout.measureAndLayout()

                assertEquals(layout.dialogWidthPx, layout.root.measuredWidth)
                assertEquals(layout.dialogHeightPx, layout.root.measuredHeight)
                layout.assertTextReadable(layout.identity)
                layout.assertTextReadable(layout.requestLabel)
                layout.assertTextReadable(layout.request)
                layout.assertTextReadable(layout.acceptanceLabel)
                layout.assertSensitiveInput(layout.acceptance)
                layout.assertRequestRemainsFullyAvailable()
                layout.assertLastFieldCanScrollIntoView()
                assertTrue("pairing evidence screenshot exists", layout.capture("pairing").isFile)
            }
        }
    }

    @Test
    fun importDialogUsesProtectedMultiLineInputWithoutHorizontalScroll() {
        listOf(
            Triple(320, 640, 1.3f),
            Triple(360, 740, 1.8f),
            Triple(640, 320, 1.8f),
        ).forEach { (widthDp, heightDp, fontScale) ->
            withImportLayout(widthDp = widthDp, heightDp = heightDp, fontScale = fontScale) { layout ->
                layout.input.setText(sampleLeaseJson())
                layout.measureAndLayout()

                assertEquals(layout.dialogWidthPx, layout.root.measuredWidth)
                layout.assertSensitiveInput(layout.input)
                layout.assertTextReadable(layout.input)
                layout.assertImportInputCanScrollIntoView()
                assertTrue("import evidence screenshot exists", layout.capture("import-$widthDp-$heightDp-$fontScale").isFile)
            }
        }
    }

    private fun withPairingLayout(
        widthDp: Int,
        heightDp: Int,
        fontScale: Float,
        assertion: (PairingMeasuredLayout) -> Unit,
    ) {
        val context = configuredContext(widthDp, heightDp, fontScale)
        InstrumentationRegistry.getInstrumentation().runOnMainSync {
            val parent = FrameLayout(context)
            val root = inflate(context, parent, R.layout.dialog_internet_pairing_completion) as ScrollView
            parent.addView(root)
            assertion(PairingMeasuredLayout(context, parent, root, layoutWidth(context, widthDp), layoutHeight(context, heightDp)))
        }
    }

    private fun withImportLayout(
        widthDp: Int,
        heightDp: Int,
        fontScale: Float,
        assertion: (ImportMeasuredLayout) -> Unit,
    ) {
        val context = configuredContext(widthDp, heightDp, fontScale)
        InstrumentationRegistry.getInstrumentation().runOnMainSync {
            val parent = FrameLayout(context)
            val root = inflate(context, parent, R.layout.dialog_internet_profile_import) as ScrollView
            parent.addView(root)
            assertion(ImportMeasuredLayout(context, parent, root, layoutWidth(context, widthDp), layoutHeight(context, heightDp)))
        }
    }

    private fun configuredContext(
        widthDp: Int,
        heightDp: Int,
        fontScale: Float,
    ): Context {
        val configuration = Configuration(applicationContext().resources.configuration)
        configuration.screenWidthDp = widthDp
        configuration.screenHeightDp = heightDp
        configuration.smallestScreenWidthDp = minOf(widthDp, heightDp)
        configuration.orientation =
            if (widthDp > heightDp) {
                Configuration.ORIENTATION_LANDSCAPE
            } else {
                Configuration.ORIENTATION_PORTRAIT
            }
        configuration.fontScale = fontScale
        val configuredContext = applicationContext().createConfigurationContext(configuration)
        return ContextThemeWrapper(configuredContext, R.style.AppTheme)
    }

    private fun inflate(
        context: Context,
        parent: ViewGroup,
        layoutId: Int,
    ): View = LayoutInflater.from(context).inflate(layoutId, parent, false)

    private fun layoutWidth(
        context: Context,
        screenWidthDp: Int,
    ): Int = dp(context, screenWidthDp - DIALOG_WINDOW_MARGIN_DP * 2)

    private fun layoutHeight(
        context: Context,
        screenHeightDp: Int,
    ): Int = dp(context, (screenHeightDp * DIALOG_MAX_HEIGHT_RATIO).roundToInt())

    private fun applicationContext(): Context = ApplicationProvider.getApplicationContext()

    private fun dp(
        context: Context,
        value: Int,
    ): Int = (value * context.resources.displayMetrics.density).roundToInt()

    private open class DialogMeasuredLayout(
        val context: Context,
        val viewport: FrameLayout,
        val root: ViewGroup,
        val dialogWidthPx: Int,
        val dialogHeightPx: Int,
    ) {
        fun measureAndLayout() {
            root.layoutParams =
                (root.layoutParams as ViewGroup.LayoutParams).apply {
                    width = ViewGroup.LayoutParams.MATCH_PARENT
                    height = dialogHeightPx
                }
            viewport.measure(
                View.MeasureSpec.makeMeasureSpec(dialogWidthPx, View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec(dialogHeightPx, View.MeasureSpec.EXACTLY),
            )
            viewport.layout(0, 0, viewport.measuredWidth, viewport.measuredHeight)
        }

        fun assertTextReadable(text: TextView) {
            val textLayout = text.layout
            assertTrue("${text.resources.getResourceEntryName(text.id)} has text layout", textLayout != null && textLayout.lineCount > 0)
            assertTrue(
                "${text.resources.getResourceEntryName(text.id)} is not ellipsized",
                (0 until textLayout.lineCount).all { line -> textLayout.getEllipsisCount(line) == 0 },
            )
            val contentWidth = text.width - text.compoundPaddingLeft - text.compoundPaddingRight
            val maximumLineWidth = (0 until textLayout.lineCount).maxOf(textLayout::getLineWidth)
            assertTrue(
                "${text.resources.getResourceEntryName(text.id)} line width $maximumLineWidth fits $contentWidth",
                maximumLineWidth <= contentWidth,
            )
        }

        fun assertSensitiveInput(input: EditText) {
            assertEquals(false, input.isSaveEnabled)
            assertEquals(View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS, input.importantForAutofill)
            assertTrue(input.inputType and InputType.TYPE_TEXT_FLAG_MULTI_LINE != 0)
            assertTrue(!input.isHorizontallyScrollable)
            assertTrue(input.imeOptions and EditorInfo.IME_FLAG_NO_PERSONALIZED_LEARNING != 0)
            assertTrue(input.measuredHeight >= dp(96))
        }

        fun capture(prefix: String): File {
            val bitmap = Bitmap.createBitmap(root.width, root.height, Bitmap.Config.ARGB_8888)
            root.draw(Canvas(bitmap))
            val outputRoot = context.getExternalFilesDir(null) ?: context.cacheDir
            val output = File(outputRoot, "internet-dialog-polish")
            assertTrue("evidence directory exists", output.isDirectory || output.mkdirs())
            val file = File(output, "$prefix-${root.width}x${root.height}.png")
            FileOutputStream(file).use { stream ->
                assertTrue(bitmap.compress(Bitmap.CompressFormat.PNG, 100, stream))
            }
            assertTrue("evidence screenshot is non-empty", file.length() > 0L)
            return file
        }

        fun dp(value: Int): Int = (value * context.resources.displayMetrics.density).roundToInt()
    }

    private class PairingMeasuredLayout(
        context: Context,
        viewport: FrameLayout,
        root: ScrollView,
        dialogWidthPx: Int,
        dialogHeightPx: Int,
    ) : DialogMeasuredLayout(context, viewport, root, dialogWidthPx, dialogHeightPx) {
        val scroll = root
        val content: ViewGroup = root.findViewById(R.id.internetPairingDialogContent)
        val identity: TextView = root.findViewById(R.id.internetPairingIdentityText)
        val requestLabel: TextView = root.findViewById(R.id.internetPairingRequestLabel)
        val request: TextView = root.findViewById(R.id.internetPairingRequestText)
        val acceptanceLabel: TextView = root.findViewById(R.id.internetPairingAcceptanceLabel)
        val acceptance: EditText = root.findViewById(R.id.internetPairingAcceptanceInput)

        fun renderSamplePayloads() {
            identity.text =
                context.getString(
                    R.string.internet_pairing_identity_format,
                    "development-macbook-pro",
                    "0123456789abcdef",
                    "fedcba9876543210",
                )
            request.text = "vibescreen://pair?v=1&o=" + "requestpayload".repeat(40)
            acceptance.setText("vibescreen://accept?v=1&a=" + "acceptancepayload".repeat(20))
        }

        fun assertRequestRemainsFullyAvailable() {
            assertTrue(request.text.startsWith("vibescreen://pair?v=1&o="))
            assertTrue(request.text.length > 200)
            assertTrue(request.isTextSelectable)
            assertTrue(!request.isHorizontallyScrollable)
        }

        fun assertLastFieldCanScrollIntoView() {
            val visibleHeight = scroll.height - scroll.paddingTop - scroll.paddingBottom
            assertTrue("dialog content should need vertical scroll on a narrow phone", content.height > visibleHeight)
            scroll.scrollTo(0, (acceptance.bottom - visibleHeight).coerceAtLeast(0))
            val visibleBottom = scroll.scrollY + visibleHeight
            assertTrue("acceptance field top is above viewport", acceptance.top >= scroll.scrollY)
            assertTrue("acceptance field bottom is below viewport", acceptance.bottom <= visibleBottom)
        }
    }

    private class ImportMeasuredLayout(
        context: Context,
        viewport: FrameLayout,
        root: ScrollView,
        dialogWidthPx: Int,
        dialogHeightPx: Int,
    ) : DialogMeasuredLayout(context, viewport, root, dialogWidthPx, dialogHeightPx) {
        val scroll = root
        val input: EditText = root.findViewById(R.id.internetProfileImportInput)

        fun assertImportInputCanScrollIntoView() {
            val visibleHeight = scroll.height - scroll.paddingTop - scroll.paddingBottom
            assertTrue("import dialog keeps a visible input area", visibleHeight > 0)
            assertTrue("import input bottom starts below top padding", input.bottom > scroll.paddingTop)
            scroll.scrollTo(0, 0)
            assertTrue("import input top is visible initially", input.top >= scroll.scrollY)
            assertTrue("import input top starts inside the viewport", input.top < scroll.scrollY + visibleHeight)
            val targetScroll = (input.bottom - visibleHeight).coerceAtLeast(0)
            scroll.scrollTo(0, targetScroll)
            val visibleBottom = scroll.scrollY + visibleHeight
            val reachedBottom = input.bottom <= visibleBottom
            val scrolledTowardBottom = targetScroll == 0 || scroll.scrollY > 0
            assertTrue("import input bottom can scroll into viewport or toward the final input lines", reachedBottom || scrolledTowardBottom)
        }
    }

    private companion object {
        const val DIALOG_WINDOW_MARGIN_DP = 24
        const val DIALOG_MAX_HEIGHT_RATIO = 0.85f
    }
}

private fun sampleLeaseJson(): String =
    """
    {
      "version": 1,
      "pairing_id": "sample",
      "pinned_host_id": "host",
      "signaling_url": "https://example.test/session",
      "signaling_session_id": "session",
      "session_epoch": 2,
      "identity_epoch": 1,
      "transcript_context": "context",
      "protocol_session_id": "protocol",
      "signaling_token": "token",
      "ice_servers": [],
      "allow_insecure_for_testing": false,
      "lease_host_key_id": "key",
      "lease_signature": "signature"
    }
    """.trimIndent()
