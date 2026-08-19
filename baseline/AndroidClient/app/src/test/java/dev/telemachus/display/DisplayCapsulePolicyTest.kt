package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class DisplayCapsulePolicyTest {
    private fun option(
        id: String,
        name: String = id,
        primary: Boolean = false,
        virtual: Boolean = false,
    ) =
        StreamDisplayOption(
            id = id,
            name = name,
            width = 1920,
            height = 1080,
            isPrimary = primary,
            isVirtual = virtual,
        )

    @Test
    fun `capsule stays collapsed unless negotiated and more than one display`() {
        val two = listOf(option("a"), option("b"))
        assertFalse(DisplayCapsulePolicy.isSelectable(displaySelection = false, displays = two))
        assertFalse(
            DisplayCapsulePolicy.isSelectable(displaySelection = true, displays = listOf(option("a"))),
        )
        assertTrue(DisplayCapsulePolicy.isSelectable(displaySelection = true, displays = two))
    }

    @Test
    fun `active option resolves by selected id`() {
        val displays = listOf(option("a", "Built-in"), option("b", "Sidecar"))
        assertEquals("Sidecar", DisplayCapsulePolicy.activeOption(displays, "b")?.name)
        assertNull(DisplayCapsulePolicy.activeOption(displays, "missing"))
    }

    @Test
    fun `label prefers selected display`() {
        val displays = listOf(option("a", "Built-in"), option("b", "Sidecar"))
        assertEquals("Sidecar", DisplayCapsulePolicy.capsuleLabel(displays, "b"))
    }

    @Test
    fun `label falls back to primary then first when selection unknown`() {
        val displays = listOf(option("a", "Built-in"), option("b", "Main", primary = true))
        assertEquals("Main", DisplayCapsulePolicy.capsuleLabel(displays, "gone"))

        val noPrimary = listOf(option("a", "First"), option("b", "Second"))
        assertEquals("First", DisplayCapsulePolicy.capsuleLabel(noPrimary, "gone"))
    }

    @Test
    fun `label is empty when there are no displays`() {
        assertEquals("", DisplayCapsulePolicy.capsuleLabel(emptyList(), "a"))
    }

    @Test
    fun `label preserves the complete trimmed name for visual and accessibility consumers`() {
        val displays = listOf(option("a", "  Studio Display Ultra Wide 5K  "))
        assertEquals("Studio Display Ultra Wide 5K", DisplayCapsulePolicy.capsuleLabel(displays, "a"))
    }
}

class ControlBarLayoutPolicyTest {
    private val geometry =
        ControlBarLayoutPolicy.Geometry(
            horizontalContentPaddingPx = 12,
            selectorMinimumWidthPx = 88,
            buttonSizePx = 48,
            actionMarginPx = 4,
            disconnectSeparationPx = 12,
            columnActionSpacingPx = 8,
            statusMinimumWidthPx = 72,
            statusGapPx = 6,
        )

    @Test
    fun `single display keeps a compact capsule`() {
        val withClipboardMinimum = compactMinimumWidth(geometry, hostActionsVisible = true, clipboardVisible = true)
        val withoutOptionalMinimum = compactMinimumWidth(geometry, hostActionsVisible = false, clipboardVisible = false)
        assertEquals(
            ControlBarLayoutPolicy.Mode.COMPACT,
            ControlBarLayoutPolicy.mode(withClipboardMinimum, false, true, true, geometry),
        )
        assertEquals(
            ControlBarLayoutPolicy.Mode.COLUMN,
            ControlBarLayoutPolicy.mode(withClipboardMinimum - 1, false, true, true, geometry),
        )
        assertEquals(
            ControlBarLayoutPolicy.Mode.COMPACT,
            ControlBarLayoutPolicy.mode(withoutOptionalMinimum, false, false, false, geometry),
        )
        assertEquals(
            ControlBarLayoutPolicy.Mode.COLUMN,
            ControlBarLayoutPolicy.mode(withoutOptionalMinimum - 1, false, false, false, geometry),
        )
    }

    @Test
    fun `common phone widths keep all negotiated controls visible without truncating actions`() {
        assertEquals(
            ControlBarLayoutPolicy.Mode.STACKED,
            ControlBarLayoutPolicy.mode(320, true, true, true, geometry),
        )
        assertEquals(
            ControlBarLayoutPolicy.Mode.STACKED,
            ControlBarLayoutPolicy.mode(360, true, true, true, geometry),
        )
    }

    @Test
    fun `selector layout changes exactly at measured pixel boundaries`() {
        val withClipboardInline = inlineMinimumWidth(geometry, hostActionsVisible = true, clipboardVisible = true)
        val withClipboardStacked = stackedMinimumWidth(geometry, hostActionsVisible = true, clipboardVisible = true)
        val withoutOptionalInline = inlineMinimumWidth(geometry, hostActionsVisible = false, clipboardVisible = false)
        val withoutOptionalStacked = stackedMinimumWidth(geometry, hostActionsVisible = false, clipboardVisible = false)
        assertEquals(
            ControlBarLayoutPolicy.Mode.INLINE,
            ControlBarLayoutPolicy.mode(withClipboardInline, true, true, true, geometry),
        )
        assertEquals(
            ControlBarLayoutPolicy.Mode.STACKED,
            ControlBarLayoutPolicy.mode(withClipboardInline - 1, true, true, true, geometry),
        )
        assertEquals(
            ControlBarLayoutPolicy.Mode.STACKED,
            ControlBarLayoutPolicy.mode(withClipboardStacked, true, true, true, geometry),
        )
        assertEquals(
            ControlBarLayoutPolicy.Mode.COLUMN,
            ControlBarLayoutPolicy.mode(withClipboardStacked - 1, true, true, true, geometry),
        )
        assertEquals(
            ControlBarLayoutPolicy.Mode.INLINE,
            ControlBarLayoutPolicy.mode(withoutOptionalInline, true, false, false, geometry),
        )
        assertEquals(
            ControlBarLayoutPolicy.Mode.STACKED,
            ControlBarLayoutPolicy.mode(withoutOptionalInline - 1, true, false, false, geometry),
        )
        assertEquals(
            ControlBarLayoutPolicy.Mode.STACKED,
            ControlBarLayoutPolicy.mode(withoutOptionalStacked, true, false, false, geometry),
        )
        assertEquals(
            ControlBarLayoutPolicy.Mode.COLUMN,
            ControlBarLayoutPolicy.mode(withoutOptionalStacked - 1, true, false, false, geometry),
        )
    }

    @Test
    fun `non integer density uses resource pixels without a one pixel overflow`() {
        val density275Geometry =
            ControlBarLayoutPolicy.Geometry(
                horizontalContentPaddingPx = 34,
                selectorMinimumWidthPx = 242,
                buttonSizePx = 132,
                actionMarginPx = 11,
                disconnectSeparationPx = 33,
                columnActionSpacingPx = 22,
                statusMinimumWidthPx = 198,
                statusGapPx = 17,
            )
        val withClipboardInline = inlineMinimumWidth(density275Geometry, hostActionsVisible = true, clipboardVisible = true)
        val withClipboardStacked =
            stackedMinimumWidth(density275Geometry, hostActionsVisible = true, clipboardVisible = true)
        val withoutOptionalInline =
            inlineMinimumWidth(density275Geometry, hostActionsVisible = false, clipboardVisible = false)
        val withoutOptionalStacked =
            stackedMinimumWidth(density275Geometry, hostActionsVisible = false, clipboardVisible = false)
        val withClipboardCompact = compactMinimumWidth(density275Geometry, hostActionsVisible = true, clipboardVisible = true)
        val withoutOptionalCompact =
            compactMinimumWidth(density275Geometry, hostActionsVisible = false, clipboardVisible = false)
        assertEquals(
            ControlBarLayoutPolicy.Mode.INLINE,
            ControlBarLayoutPolicy.mode(withClipboardInline, true, true, true, density275Geometry),
        )
        assertEquals(
            ControlBarLayoutPolicy.Mode.STACKED,
            ControlBarLayoutPolicy.mode(withClipboardInline - 1, true, true, true, density275Geometry),
        )
        assertEquals(
            ControlBarLayoutPolicy.Mode.STACKED,
            ControlBarLayoutPolicy.mode(withClipboardStacked, true, true, true, density275Geometry),
        )
        assertEquals(
            ControlBarLayoutPolicy.Mode.COLUMN,
            ControlBarLayoutPolicy.mode(withClipboardStacked - 1, true, true, true, density275Geometry),
        )
        assertEquals(
            ControlBarLayoutPolicy.Mode.INLINE,
            ControlBarLayoutPolicy.mode(withoutOptionalInline, true, false, false, density275Geometry),
        )
        assertEquals(
            ControlBarLayoutPolicy.Mode.STACKED,
            ControlBarLayoutPolicy.mode(withoutOptionalInline - 1, true, false, false, density275Geometry),
        )
        assertEquals(
            ControlBarLayoutPolicy.Mode.STACKED,
            ControlBarLayoutPolicy.mode(withoutOptionalStacked, true, false, false, density275Geometry),
        )
        assertEquals(
            ControlBarLayoutPolicy.Mode.COLUMN,
            ControlBarLayoutPolicy.mode(withoutOptionalStacked - 1, true, false, false, density275Geometry),
        )
        assertEquals(
            ControlBarLayoutPolicy.Mode.COMPACT,
            ControlBarLayoutPolicy.mode(withClipboardCompact, false, true, true, density275Geometry),
        )
        assertEquals(
            ControlBarLayoutPolicy.Mode.COLUMN,
            ControlBarLayoutPolicy.mode(withClipboardCompact - 1, false, true, true, density275Geometry),
        )
        assertEquals(
            ControlBarLayoutPolicy.Mode.COMPACT,
            ControlBarLayoutPolicy.mode(withoutOptionalCompact, false, false, false, density275Geometry),
        )
        assertEquals(
            ControlBarLayoutPolicy.Mode.COLUMN,
            ControlBarLayoutPolicy.mode(withoutOptionalCompact - 1, false, false, false, density275Geometry),
        )
    }

    @Test
    fun `column mode converts horizontal action spacing to vertical spacing`() {
        assertEquals(
            ControlBarLayoutPolicy.Margins(0, 8, 0),
            ControlBarLayoutPolicy.actionMargins(
                ControlBarLayoutPolicy.Mode.COLUMN,
                ControlBarLayoutPolicy.Action.SETTINGS,
                hostActionsVisible = true,
                clipboardVisible = true,
                geometry = geometry,
            ),
        )
        assertEquals(
            ControlBarLayoutPolicy.Margins(0, 12, 0),
            ControlBarLayoutPolicy.actionMargins(
                ControlBarLayoutPolicy.Mode.COLUMN,
                ControlBarLayoutPolicy.Action.DISCONNECT,
                hostActionsVisible = true,
                clipboardVisible = true,
                geometry = geometry,
            ),
        )
        assertEquals(
            ControlBarLayoutPolicy.Margins(12, 0, 0),
            ControlBarLayoutPolicy.actionMargins(
                ControlBarLayoutPolicy.Mode.INLINE,
                ControlBarLayoutPolicy.Action.DISCONNECT,
                hostActionsVisible = true,
                clipboardVisible = true,
                geometry = geometry,
            ),
        )
    }

    @Test
    fun `stream status consumes explicit space and stacks before truncating actions`() {
        val inlineMinimum = inlineMinimumWidth(geometry, hostActionsVisible = true, clipboardVisible = false)
        assertEquals(
            ControlBarLayoutPolicy.Mode.INLINE,
            ControlBarLayoutPolicy.mode(inlineMinimum, true, true, false, geometry),
        )
        assertEquals(
            ControlBarLayoutPolicy.Margins(0, 0, 6),
            ControlBarLayoutPolicy.statusMargins(ControlBarLayoutPolicy.Mode.INLINE, geometry),
        )
        assertEquals(
            ControlBarLayoutPolicy.Margins(0, 0, 0, 6),
            ControlBarLayoutPolicy.statusMargins(ControlBarLayoutPolicy.Mode.STACKED, geometry),
        )
    }

    private fun compactMinimumWidth(
        geometry: ControlBarLayoutPolicy.Geometry,
        hostActionsVisible: Boolean,
        clipboardVisible: Boolean,
    ): Int =
        geometry.horizontalContentPaddingPx +
            statusWidth(geometry) +
            geometry.horizontalActionsWidthPx(hostActionsVisible, clipboardVisible)

    private fun inlineMinimumWidth(
        geometry: ControlBarLayoutPolicy.Geometry,
        hostActionsVisible: Boolean,
        clipboardVisible: Boolean,
    ): Int =
        compactMinimumWidth(geometry, hostActionsVisible, clipboardVisible) + geometry.selectorMinimumWidthPx

    private fun stackedMinimumWidth(
        geometry: ControlBarLayoutPolicy.Geometry,
        hostActionsVisible: Boolean,
        clipboardVisible: Boolean,
    ): Int =
        geometry.horizontalContentPaddingPx +
            maxOf(
                geometry.statusMinimumWidthPx,
                geometry.selectorMinimumWidthPx,
                geometry.horizontalActionsWidthPx(hostActionsVisible, clipboardVisible),
            )

    private fun statusWidth(geometry: ControlBarLayoutPolicy.Geometry): Int =
        geometry.statusMinimumWidthPx + geometry.statusGapPx
}

class ControlBarAccessibilityPolicyTest {
    @Test
    fun `transient controls auto hide for standard touch navigation`() {
        assertTrue(ControlBarAccessibilityPolicy.shouldAutoHide(touchExplorationEnabled = false))
        assertEquals(5_000L, ControlBarAccessibilityPolicy.STANDARD_AUTO_HIDE_MS)
    }

    @Test
    fun `transient controls remain available during touch exploration`() {
        assertFalse(ControlBarAccessibilityPolicy.shouldAutoHide(touchExplorationEnabled = true))
    }

    @Test
    fun `session-start reveal stays visible longer than a manual reveal`() {
        assertEquals(
            ControlBarAccessibilityPolicy.STANDARD_AUTO_HIDE_MS,
            ControlBarAccessibilityPolicy.autoHideDelayMs(
                touchExplorationEnabled = false,
                revealReason = ControlBarAccessibilityPolicy.RevealReason.USER_REQUEST,
            ),
        )
        assertEquals(
            ControlBarAccessibilityPolicy.SESSION_STARTED_AUTO_HIDE_MS,
            ControlBarAccessibilityPolicy.autoHideDelayMs(
                touchExplorationEnabled = false,
                revealReason = ControlBarAccessibilityPolicy.RevealReason.SESSION_STARTED,
            ),
        )
        assertTrue(
            ControlBarAccessibilityPolicy.SESSION_STARTED_AUTO_HIDE_MS >
                ControlBarAccessibilityPolicy.STANDARD_AUTO_HIDE_MS,
        )
    }

    @Test
    fun `touch exploration disables every auto-hide delay`() {
        ControlBarAccessibilityPolicy.RevealReason.entries.forEach { reason ->
            assertNull(
                ControlBarAccessibilityPolicy.autoHideDelayMs(
                    touchExplorationEnabled = true,
                    revealReason = reason,
                ),
            )
        }
    }

    @Test
    fun `reveal action is exposed only for connected sessions with hidden controls`() {
        assertTrue(
            ControlBarAccessibilityPolicy.shouldExposeRevealAction(
                connected = true,
                controlBarVisible = false,
            ),
        )
        assertFalse(
            ControlBarAccessibilityPolicy.shouldExposeRevealAction(
                connected = true,
                controlBarVisible = true,
            ),
        )
        assertFalse(
            ControlBarAccessibilityPolicy.shouldExposeRevealAction(
                connected = false,
                controlBarVisible = false,
            ),
        )
    }
}
