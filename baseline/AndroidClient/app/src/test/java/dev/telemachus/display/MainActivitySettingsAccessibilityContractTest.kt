package dev.telemachus.display

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class MainActivitySettingsAccessibilityContractTest {
    @Test
    fun unavailableVideoAndGestureControlsUseSharedAccessibilityApplier() {
        val source = mainActivitySource()
        val layout = settingsLayoutSource()
        val videoControls = extractMethod(source, "private fun setupVideoControls")
        val gestureControls = extractMethod(source, "private fun setupGestureShortcutControls")
        val applier = settingsUnavailableControlsAccessibilityApplierSource()

        assertTrue(
            "Video controls should route unavailable semantics through the shared Settings applier",
            videoControls.contains("SettingsUnavailableControlsAccessibilityApplier.apply(") &&
                videoControls.contains("unavailableContent = videoStaticContent + listOf(qualityGroup, frameRateGroup, bitrateSlider, bitrateValue)"),
        )
        assertTrue(
            "Gesture controls should route unavailable semantics through the shared Settings applier",
            gestureControls.contains("SettingsUnavailableControlsAccessibilityApplier.apply(") &&
                gestureControls.contains("unavailableContent = gestureStaticContent + listOf(swipeUpGroup, swipeDownGroup)"),
        )
        assertTrue(
            "Video unavailable state should hide labels, values, and controls from accessibility traversal",
            videoControls.contains("videoStaticContent: List<View>") &&
                source.contains("videoStaticContent = listOf(videoQualityLabel, videoFrameRateLabel, videoBitrateLabel)") &&
                source.contains("findViewById<TextView>(R.id.videoBitrateValue)"),
        )
        assertTrue(
            "Gesture unavailable state should hide inactive labels and controls from accessibility traversal",
            gestureControls.contains("gestureStaticContent: List<View>") &&
                source.contains("gestureStaticContent = listOf(gestureShortcutsDescription, gestureSwipeUpLabel, gestureSwipeDownLabel)"),
        )
        assertTrue(
            "Unavailable notes should become the single accessible explanation",
            applier.contains("unavailableNote.visibility = if (available) View.GONE else View.VISIBLE") &&
                applier.contains("unavailableNote.isFocusable = !available") &&
                applier.contains("View.IMPORTANT_FOR_ACCESSIBILITY_YES"),
        )
        assertTrue(
            "Disabled option groups should not remain exposed as dead controls",
            applier.contains("View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS") &&
                applier.contains("View.IMPORTANT_FOR_ACCESSIBILITY_NO"),
        )
        assertTrue(
            "Available controls should restore the platform default accessibility importance",
            applier.contains("View.IMPORTANT_FOR_ACCESSIBILITY_AUTO"),
        )
        assertFalse(
            "The Activity should not hand-roll unavailable-note visibility outside the shared applier",
            Regex("unavailableNote\\.visibility\\s*=").containsMatchIn(videoControls) ||
                Regex("unavailableNote\\.visibility\\s*=").containsMatchIn(gestureControls),
        )
        assertTrue(
            "Focusable unavailable notes should have a visible focus background",
            extractXmlElement(layout, "android:id=\"@+id/videoControlUnavailable\"")
                .contains("android:background=\"?attr/selectableItemBackground\"") &&
                extractXmlElement(layout, "android:id=\"@+id/gestureShortcutUnavailable\"")
                    .contains("android:background=\"?attr/selectableItemBackground\""),
        )
        listOf(
            "android:id=\"@+id/videoQualityLabel\"" to "android:text=\"@string/video_quality_label\"",
            "android:id=\"@+id/videoFrameRateLabel\"" to "android:text=\"@string/video_frame_rate_label\"",
            "android:id=\"@+id/videoBitrateLabel\"" to "android:text=\"@string/video_bitrate_label\"",
            "android:id=\"@+id/gestureShortcutsDescription\"" to "android:text=\"@string/gesture_shortcuts_description\"",
            "android:id=\"@+id/gestureSwipeUpLabel\"" to "android:text=\"@string/gesture_swipe_up_label\"",
            "android:id=\"@+id/gestureSwipeDownLabel\"" to "android:text=\"@string/gesture_swipe_down_label\"",
        ).forEach { (idAttribute, expectedText) ->
            assertTrue(
                "$idAttribute should be attached to $expectedText",
                extractXmlElement(layout, idAttribute).contains(expectedText),
            )
        }
    }

    private fun mainActivitySource(): String = sourceFile(MAIN_ACTIVITY_PATHS).readText()

    private fun settingsLayoutSource(): String = sourceFile(SETTINGS_LAYOUT_PATHS).readText()

    private fun settingsUnavailableControlsAccessibilityApplierSource(): String =
        sourceFile(SETTINGS_UNAVAILABLE_CONTROLS_ACCESSIBILITY_APPLIER_PATHS).readText()

    private fun sourceFile(paths: List<String>): File {
        var current = File(requireNotNull(System.getProperty("user.dir"))).canonicalFile
        repeat(8) {
            paths
                .map(current::resolve)
                .firstOrNull(File::isFile)
                ?.let { return it }
            current = current.parentFile?.canonicalFile ?: current
        }
        error("Source file not found from " + System.getProperty("user.dir"))
    }

    private fun extractMethod(
        source: String,
        signature: String,
    ): String {
        val start = source.indexOf(signature)
        require(start >= 0) { "Method not found: $signature" }
        val bodyStart = source.indexOf('{', start)
        require(bodyStart >= 0) { "Method body not found: $signature" }
        var depth = 0
        for (index in bodyStart until source.length) {
            when (source[index]) {
                '{' -> depth++
                '}' -> {
                    depth--
                    if (depth == 0) return source.substring(start, index + 1)
                }
            }
        }
        error("Closing brace not found: $signature")
    }

    private fun extractXmlElement(
        source: String,
        idAttribute: String,
    ): String {
        val idIndex = source.indexOf(idAttribute)
        require(idIndex >= 0) { "XML element not found: $idAttribute" }
        val openStart = source.lastIndexOf('<', idIndex)
        require(openStart >= 0) { "XML element start not found: $idAttribute" }
        val openTagEnd = source.indexOf('>', idIndex)
        require(openTagEnd >= 0) { "XML element open tag end not found: $idAttribute" }
        return source.substring(openStart, openTagEnd + 1)
    }

    private companion object {
        val MAIN_ACTIVITY_PATHS =
            listOf(
                "app/src/main/java/dev/telemachus/display/MainActivity.kt",
                "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/MainActivity.kt",
            )
        val SETTINGS_LAYOUT_PATHS =
            listOf(
                "app/src/main/res/layout/dialog_settings.xml",
                "baseline/AndroidClient/app/src/main/res/layout/dialog_settings.xml",
            )
        val SETTINGS_UNAVAILABLE_CONTROLS_ACCESSIBILITY_APPLIER_PATHS =
            listOf(
                "app/src/main/java/dev/telemachus/display/SettingsUnavailableControlsAccessibilityApplier.kt",
                "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/SettingsUnavailableControlsAccessibilityApplier.kt",
            )
    }
}
