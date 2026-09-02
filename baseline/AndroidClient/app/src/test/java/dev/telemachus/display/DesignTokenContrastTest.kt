package dev.telemachus.display

import java.io.File
import javax.xml.parsers.DocumentBuilderFactory
import kotlin.math.max
import kotlin.math.min
import org.junit.Assert.assertTrue
import org.junit.Test

class DesignTokenContrastTest {
    @Test
    fun lightSmallTextTokensMeetWcagContrast() {
        val colors = colors("values/colors.xml")
        val textTokens = listOf("on_surface_muted", "on_surface_subtle", "on_surface_faint")
        val backgrounds = lightTextBackgrounds()

        textTokens.forEach { textToken ->
            backgrounds.forEach { backgroundToken ->
                val ratio = contrastRatio(
                    colors.resolveToken(textToken, backgroundToken),
                    colors.resolveBackground(backgroundToken),
                )
                assertTrue(
                    "$textToken on ${backgroundToken.name} contrast ${"%.2f".format(ratio)} is below 4.5:1",
                    ratio >= MINIMUM_SMALL_TEXT_CONTRAST,
                )
            }
        }
    }

    @Test
    fun darkSmallTextTokensMeetWcagContrast() {
        val colors = colors("values-night/colors.xml")
        val textTokens = listOf("on_surface_muted", "on_surface_subtle", "on_surface_faint")

        textTokens.forEach { textToken ->
            darkTextBackgrounds().forEach { backgroundToken ->
                val ratio = contrastRatio(
                    colors.resolveToken(textToken, backgroundToken),
                    colors.resolveBackground(backgroundToken),
                )
                assertTrue(
                    "$textToken on ${backgroundToken.name} contrast ${"%.2f".format(ratio)} is below 4.5:1",
                    ratio >= MINIMUM_SMALL_TEXT_CONTRAST,
                )
            }
        }
    }

    @Test
    fun lightMutedSubtleAndFaintTokensKeepVisibilityHierarchy() {
        val colors = colors("values/colors.xml")
        val muted = colors.resolveToken("on_surface_muted").relativeLuminance()
        val subtle = colors.resolveToken("on_surface_subtle").relativeLuminance()
        val faint = colors.resolveToken("on_surface_faint").relativeLuminance()

        assertTrue("on_surface_muted should be more prominent than on_surface_subtle", muted < subtle)
        assertTrue("on_surface_subtle should be more prominent than on_surface_faint", subtle < faint)
    }

    @Test
    fun lightUncheckedSwitchTokensKeepTrackAndThumbDistinct() {
        val colors = colors("values/colors.xml")
        assertUncheckedSwitchTokensKeepTrackAndThumbDistinct(colors, lightSwitchBackgrounds())
    }

    @Test
    fun lightOutlineStrongTokenMeetsNonTextContrast() {
        val colors = colors("values/colors.xml")
        assertOutlineStrongTokenMeetsNonTextContrast(colors, lightOutlineBackgrounds())
    }

    @Test
    fun darkOutlineStrongTokenMeetsNonTextContrast() {
        val colors = colors("values-night/colors.xml")
        assertOutlineStrongTokenMeetsNonTextContrast(colors, darkOutlineBackgrounds())
    }

    @Test
    fun lightModeToggleStrokeMeetsNonTextContrastInAllStates() {
        val colors = colors("values/colors.xml")
        assertModeToggleStrokeMeetsNonTextContrast(colors)
    }

    @Test
    fun darkModeToggleStrokeMeetsNonTextContrastInAllStates() {
        val colors = colors("values-night/colors.xml")
        assertModeToggleStrokeMeetsNonTextContrast(colors)
    }

    private fun assertOutlineStrongTokenMeetsNonTextContrast(
        colors: Map<String, String>,
        backgrounds: List<BackgroundSpec>,
    ) {
        backgrounds.forEach { backgroundToken ->
            val ratio = contrastRatio(
                colors.resolveToken("outline_strong", backgroundToken),
                colors.resolveBackground(backgroundToken),
            )
            assertTrue(
                "outline_strong on ${backgroundToken.name} contrast ${"%.2f".format(ratio)} is below 3.0:1",
                ratio >= MINIMUM_NON_TEXT_CONTRAST,
            )
        }
    }

    private fun assertModeToggleStrokeMeetsNonTextContrast(colors: Map<String, String>) {
        val toggleBackgroundSelector = colorSelector("color/mode_toggle_bg.xml")
        val toggleStrokeSelector = colorSelector("color/mode_toggle_stroke.xml")

        val checkedBackground = colors.resolveToken(toggleBackgroundSelector.checkedToken)
        val checkedStroke = colors.resolveTokenOver(toggleStrokeSelector.checkedToken, checkedBackground)
        val checkedRatio = contrastRatio(checkedStroke, checkedBackground)
        assertTrue(
            "mode_toggle_stroke checked contrast ${"%.2f".format(checkedRatio)} is below 3.0:1",
            checkedRatio >= MINIMUM_NON_TEXT_CONTRAST,
        )

        val uncheckedBackground = colors.resolveToken(toggleBackgroundSelector.defaultToken)
        val uncheckedStroke = colors.resolveTokenOver(toggleStrokeSelector.defaultToken, uncheckedBackground)
        val uncheckedRatio = contrastRatio(uncheckedStroke, uncheckedBackground)
        assertTrue(
            "mode_toggle_stroke default contrast ${"%.2f".format(uncheckedRatio)} is below 3.0:1",
            uncheckedRatio >= MINIMUM_NON_TEXT_CONTRAST,
        )
    }

    @Test
    fun darkUncheckedSwitchTokensKeepTrackAndThumbDistinct() {
        val colors = colors("values-night/colors.xml")
        assertUncheckedSwitchTokensKeepTrackAndThumbDistinct(colors, darkSwitchBackgrounds())
    }

    private fun assertUncheckedSwitchTokensKeepTrackAndThumbDistinct(
        colors: Map<String, String>,
        backgrounds: List<BackgroundSpec>,
    ) {
        backgrounds.forEach { backgroundToken ->
            val background = colors.resolveBackground(backgroundToken)
            val track = colors.resolveToken("switch_track_unchecked", backgroundToken)
            val ratio = contrastRatio(track, background)
            assertTrue(
                "switch_track_unchecked on ${backgroundToken.name} contrast ${"%.2f".format(ratio)} is below 3.0:1",
                ratio >= MINIMUM_NON_TEXT_CONTRAST,
            )

            val thumb = colors.resolveTokenOver("switch_thumb_unchecked", track)
            val thumbRatio = contrastRatio(thumb, track)
            assertTrue(
                "switch_thumb_unchecked on switch_track_unchecked contrast ${"%.2f".format(thumbRatio)} is below 3.0:1",
                thumbRatio >= MINIMUM_NON_TEXT_CONTRAST,
            )
        }
    }

    private fun colors(path: String): Map<String, String> {
        val file = resourceFile(path)
        val document = DocumentBuilderFactory.newInstance().newDocumentBuilder().parse(file)
        val nodes = document.getElementsByTagName("color")
        return buildMap {
            for (index in 0 until nodes.length) {
                val node = nodes.item(index)
                val name = node.attributes.getNamedItem("name").nodeValue
                put(name, node.textContent.trim())
            }
        }
    }

    private fun colorSelector(path: String): ColorSelector {
        val file = resourceFile(path)
        val document = DocumentBuilderFactory.newInstance().newDocumentBuilder().parse(file)
        val nodes = document.getElementsByTagName("item")
        var checkedToken: String? = null
        var defaultToken: String? = null
        for (index in 0 until nodes.length) {
            val node = nodes.item(index)
            val color = node.attributes.getNamedItem("android:color")?.nodeValue ?: continue
            val token = color.removePrefix("@color/")
            val enabled = node.attributes.getNamedItem("android:state_enabled")?.nodeValue?.toBooleanStrictOrNull()
            if (enabled == false) continue
            val checked = node.attributes.getNamedItem("android:state_checked")?.nodeValue?.toBooleanStrictOrNull()
            when (checked) {
                true -> checkedToken = token
                null -> defaultToken = defaultToken ?: token
                false -> defaultToken = defaultToken ?: token
            }
        }
        return ColorSelector(
            checkedToken = requireNotNull(checkedToken) { "Missing checked color in $path" },
            defaultToken = requireNotNull(defaultToken) { "Missing default color in $path" },
        )
    }

    private fun resourceFile(path: String): File {
        val candidates =
            listOf(
                File(path),
                File("src/main/res", path),
                File("app/src/main/res", path),
                File("baseline/AndroidClient/app/src/main/res", path),
            )
        return candidates.firstOrNull { it.isFile } ?: error("Missing resource file $path")
    }

    private fun Map<String, String>.resolveToken(
        token: String,
        backgroundToken: BackgroundSpec = SURFACE_BACKGROUND,
    ): Rgb {
        val color = requireNotNull(this[token]) { "Missing color token $token" }
        return parseColor(color).compositeOver(resolveBackground(backgroundToken))
    }

    private fun Map<String, String>.resolveTokenOver(
        token: String,
        background: Rgb,
    ): Rgb {
        val color = requireNotNull(this[token]) { "Missing color token $token" }
        return parseColor(color).compositeOver(background)
    }

    private fun Map<String, String>.resolveBackground(background: BackgroundSpec): Rgb {
        val color = requireNotNull(this[background.token]) { "Missing color token ${background.token}" }
        val base = background.base?.let { resolveBackground(it) } ?: WHITE
        return parseColor(color).compositeOver(base)
    }

    private fun parseColor(value: String): Rgba {
        val hex = value.removePrefix("#")
        require(hex.length == 6 || hex.length == 8) { "Unsupported color value $value" }
        val offset = if (hex.length == 8) 2 else 0
        val alpha = if (hex.length == 8) hex.substring(0, 2).toInt(16) / 255.0 else 1.0
        return Rgba(
            red = hex.substring(offset, offset + 2).toInt(16),
            green = hex.substring(offset + 2, offset + 4).toInt(16),
            blue = hex.substring(offset + 4, offset + 6).toInt(16),
            alpha = alpha,
        )
    }

    private fun contrastRatio(
        first: Rgb,
        second: Rgb,
    ): Double {
        val firstLuminance = first.relativeLuminance()
        val secondLuminance = second.relativeLuminance()
        return (max(firstLuminance, secondLuminance) + LUMINANCE_OFFSET) /
            (min(firstLuminance, secondLuminance) + LUMINANCE_OFFSET)
    }

    private fun Rgba.compositeOver(background: Rgb): Rgb =
        Rgb(
            red = compositeChannel(red, background.red),
            green = compositeChannel(green, background.green),
            blue = compositeChannel(blue, background.blue),
        )

    private fun Rgba.compositeChannel(
        foreground: Int,
        background: Int,
    ): Int = (foreground * alpha + background * (1.0 - alpha)).toInt()

    private fun Rgb.relativeLuminance(): Double =
        RED_LUMINANCE * red.linearize() +
            GREEN_LUMINANCE * green.linearize() +
            BLUE_LUMINANCE * blue.linearize()

    private fun Int.linearize(): Double {
        val channel = this / RGB_CHANNEL_MAX
        return if (channel <= SRGB_LINEAR_THRESHOLD) {
            channel / SRGB_LINEAR_DIVISOR
        } else {
            Math.pow((channel + SRGB_OFFSET) / SRGB_SCALE, SRGB_EXPONENT)
        }
    }

    private data class Rgb(
        val red: Int,
        val green: Int,
        val blue: Int,
    )

    private data class Rgba(
        val red: Int,
        val green: Int,
        val blue: Int,
        val alpha: Double,
    )

    private data class BackgroundSpec(
        val name: String,
        val token: String,
        val base: BackgroundSpec? = null,
    )

    private data class ColorSelector(
        val checkedToken: String,
        val defaultToken: String,
    )

    private companion object {
        val SURFACE_BACKGROUND = BackgroundSpec("surface", "surface")
        val RAISED_BACKGROUND = BackgroundSpec("surface_raised", "surface_raised", SURFACE_BACKGROUND)
        val PANEL_BACKGROUND = BackgroundSpec("surface_panel", "surface_panel", SURFACE_BACKGROUND)
        val SCRIM_BACKGROUND = BackgroundSpec("surface_scrim", "surface_scrim", SURFACE_BACKGROUND)
        val INSTRUCTION_BACKGROUND = BackgroundSpec("instruction_bg", "surface_hairline", SURFACE_BACKGROUND)
        val SETTINGS_ITEM_BACKGROUND = BackgroundSpec("settings_item_bg", "surface_hairline", RAISED_BACKGROUND)
        const val MINIMUM_SMALL_TEXT_CONTRAST = 4.5
        const val MINIMUM_NON_TEXT_CONTRAST = 3.0
        const val RED_LUMINANCE = 0.2126
        const val GREEN_LUMINANCE = 0.7152
        const val BLUE_LUMINANCE = 0.0722
        const val LUMINANCE_OFFSET = 0.05
        const val RGB_CHANNEL_MAX = 255.0
        const val SRGB_LINEAR_THRESHOLD = 0.04045
        const val SRGB_LINEAR_DIVISOR = 12.92
        const val SRGB_OFFSET = 0.055
        const val SRGB_SCALE = 1.055
        const val SRGB_EXPONENT = 2.4
        val WHITE = Rgb(255, 255, 255)

        fun lightTextBackgrounds(): List<BackgroundSpec> =
            listOf(
                SURFACE_BACKGROUND,
                RAISED_BACKGROUND,
                PANEL_BACKGROUND,
                SCRIM_BACKGROUND,
                INSTRUCTION_BACKGROUND,
                SETTINGS_ITEM_BACKGROUND,
            )

        fun darkTextBackgrounds(): List<BackgroundSpec> = lightTextBackgrounds()

        fun lightSwitchBackgrounds(): List<BackgroundSpec> = listOf(SETTINGS_ITEM_BACKGROUND)

        fun lightOutlineBackgrounds(): List<BackgroundSpec> =
            listOf(
                SURFACE_BACKGROUND,
                RAISED_BACKGROUND,
                PANEL_BACKGROUND,
                SCRIM_BACKGROUND,
                INSTRUCTION_BACKGROUND,
                SETTINGS_ITEM_BACKGROUND,
            )

        fun darkOutlineBackgrounds(): List<BackgroundSpec> = lightOutlineBackgrounds()

        fun darkSwitchBackgrounds(): List<BackgroundSpec> = lightSwitchBackgrounds()
    }
}
