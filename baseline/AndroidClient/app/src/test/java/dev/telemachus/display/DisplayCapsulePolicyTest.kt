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
    fun `capsule disables while a display switch is pending`() {
        val displays = listOf(option("a"), option("b"))

        assertTrue(DisplayCapsulePolicy.isEnabled(displaySelection = true, displays = displays, pendingDisplayId = null))
        assertFalse(DisplayCapsulePolicy.isEnabled(displaySelection = true, displays = displays, pendingDisplayId = "b"))
    }

    @Test
    fun `active option resolves by selected id`() {
        val displays = listOf(option("a", "Built-in"), option("b", "Sidecar"))
        assertEquals("Sidecar", DisplayCapsulePolicy.activeOption(displays, "b")?.name)
        assertNull(DisplayCapsulePolicy.activeOption(displays, "missing"))
    }

    @Test
    fun `pending option resolves only known requested display`() {
        val displays = listOf(option("a", "Built-in"), option("b", "Sidecar"))

        assertEquals("Sidecar", DisplayCapsulePolicy.pendingOption(displays, "b")?.name)
        assertNull(DisplayCapsulePolicy.pendingOption(displays, null))
        assertNull(DisplayCapsulePolicy.pendingOption(displays, "missing"))
    }

    @Test
    fun `text state preserves pending switch even when target display is missing`() {
        val state =
            DisplayCapsulePolicy.textState(
                displays = listOf(option("a", "Built-in", primary = true)),
                selectedId = "a",
                pendingId = "removed",
            )

        assertEquals("Built-in", state.activeLabel)
        assertNull(state.pendingLabel)
        assertTrue(state.switching)
    }

    @Test
    fun `text state includes trimmed pending display name when known`() {
        val state =
            DisplayCapsulePolicy.textState(
                displays = listOf(option("a", "Built-in"), option("b", "  Sidecar  ")),
                selectedId = "a",
                pendingId = "b",
            )

        assertEquals("Built-in", state.activeLabel)
        assertEquals("Sidecar", state.pendingLabel)
        assertTrue(state.switching)
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

    @Test
    fun menuKindDistinguishesPrimaryVirtualBuiltInAndExternalDisplays() {
        assertEquals(
            DisplayCapsulePolicy.DisplayKind.PRIMARY,
            DisplayCapsulePolicy.displayKind(option("main", "Studio Display", primary = true)),
        )
        assertEquals(
            DisplayCapsulePolicy.DisplayKind.VIRTUAL,
            DisplayCapsulePolicy.displayKind(option("virtual", "Vibe Screen", primary = true, virtual = true)),
        )
        assertEquals(
            DisplayCapsulePolicy.DisplayKind.BUILT_IN,
            DisplayCapsulePolicy.displayKind(option("built", "Built-in Retina Display")),
        )
        assertEquals(
            DisplayCapsulePolicy.DisplayKind.EXTERNAL,
            DisplayCapsulePolicy.displayKind(option("external", "Studio Display")),
        )
    }

    @Test
    fun displayMenuIgnoresSelectionsBeforeItIsArmed() {
        assertFalse(
            DisplayMenuSelectionGuard.acceptsSelection(
                menuShownAtMs = -1,
                nowMs = 1_000,
                armDelayMs = 300,
            ),
        )
        assertFalse(
            DisplayMenuSelectionGuard.acceptsSelection(
                menuShownAtMs = 1_000,
                nowMs = 1_299,
                armDelayMs = 300,
            ),
        )
        assertTrue(
            DisplayMenuSelectionGuard.acceptsSelection(
                menuShownAtMs = 1_000,
                nowMs = 1_300,
                armDelayMs = 300,
            ),
        )
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
            ControlBarLayoutPolicy.Margins(0, 8, 0),
            ControlBarLayoutPolicy.actionMargins(
                ControlBarLayoutPolicy.Mode.COLUMN,
                ControlBarLayoutPolicy.Action.FILE_TRANSFER,
                hostActionsVisible = false,
                clipboardVisible = true,
                geometry = geometry,
                fileTransferVisible = true,
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
    fun `file transfer control consumes action width only when visible`() {
        val withoutFileTransfer = compactMinimumWidth(geometry, hostActionsVisible = true, clipboardVisible = true)
        val withFileTransfer =
            compactMinimumWidth(
                geometry,
                hostActionsVisible = true,
                clipboardVisible = true,
                fileTransferVisible = true,
            )
        assertEquals(geometry.buttonSizePx + geometry.actionMarginPx * 2, withFileTransfer - withoutFileTransfer)
        assertEquals(
            ControlBarLayoutPolicy.Mode.COMPACT,
            ControlBarLayoutPolicy.mode(
                withFileTransfer,
                displaySelectorVisible = false,
                hostActionsVisible = true,
                clipboardVisible = true,
                geometry = geometry,
                fileTransferVisible = true,
            ),
        )
        assertEquals(
            ControlBarLayoutPolicy.Mode.COLUMN,
            ControlBarLayoutPolicy.mode(
                withFileTransfer - 1,
                displaySelectorVisible = false,
                hostActionsVisible = true,
                clipboardVisible = true,
                geometry = geometry,
                fileTransferVisible = true,
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
        fileTransferVisible: Boolean = false,
    ): Int =
        geometry.horizontalContentPaddingPx +
            statusWidth(geometry) +
            geometry.horizontalActionsWidthPx(hostActionsVisible, clipboardVisible, fileTransferVisible)

    private fun inlineMinimumWidth(
        geometry: ControlBarLayoutPolicy.Geometry,
        hostActionsVisible: Boolean,
        clipboardVisible: Boolean,
        fileTransferVisible: Boolean = false,
    ): Int =
        compactMinimumWidth(geometry, hostActionsVisible, clipboardVisible, fileTransferVisible) +
            geometry.selectorMinimumWidthPx

    private fun stackedMinimumWidth(
        geometry: ControlBarLayoutPolicy.Geometry,
        hostActionsVisible: Boolean,
        clipboardVisible: Boolean,
        fileTransferVisible: Boolean = false,
    ): Int =
        geometry.horizontalContentPaddingPx +
            maxOf(
                geometry.statusMinimumWidthPx,
                geometry.selectorMinimumWidthPx,
                geometry.horizontalActionsWidthPx(hostActionsVisible, clipboardVisible, fileTransferVisible),
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

class ControlRevealGesturePolicyTest {
    @Test
    fun hiddenControlsConsumeOnlyTheFirstDirectTouchInsideTheRevealHotZone() {
        assertTrue(
            ControlRevealGesturePolicy.shouldStartRevealOnlyGesture(
                connected = true,
                controlBarVisible = false,
                directTouch = true,
                inRevealHotZone = true,
                phase = StreamTouchPhase.BEGIN,
            ),
        )
        assertTrue(
            ControlRevealGesturePolicy.shouldConsumeActiveRevealOnlyGesture(
                revealOnlyGestureActive = true,
                directTouch = true,
                phase = StreamTouchPhase.BEGIN,
            ),
        )
        assertTrue(
            ControlRevealGesturePolicy.shouldConsumeActiveRevealOnlyGesture(
                revealOnlyGestureActive = true,
                directTouch = true,
                phase = StreamTouchPhase.UPDATE,
            ),
        )
        assertTrue(ControlRevealGesturePolicy.endsGesture(StreamTouchPhase.END))
    }

    @Test
    fun streamBodyTouchesAndVisibleControlsContinueThroughToTheMac() {
        assertFalse(
            ControlRevealGesturePolicy.shouldStartRevealOnlyGesture(
                connected = true,
                controlBarVisible = false,
                directTouch = true,
                inRevealHotZone = false,
                phase = StreamTouchPhase.BEGIN,
            ),
        )
        assertFalse(
            ControlRevealGesturePolicy.shouldStartRevealOnlyGesture(
                connected = true,
                controlBarVisible = true,
                directTouch = true,
                inRevealHotZone = true,
                phase = StreamTouchPhase.BEGIN,
            ),
        )
    }

    @Test
    fun stylusAndPointerGesturesAreNeverConvertedToRevealOnlyGestures() {
        assertFalse(
            ControlRevealGesturePolicy.shouldStartRevealOnlyGesture(
                connected = true,
                controlBarVisible = false,
                directTouch = false,
                inRevealHotZone = true,
                phase = StreamTouchPhase.BEGIN,
            ),
        )
        assertFalse(
            ControlRevealGesturePolicy.shouldConsumeActiveRevealOnlyGesture(
                revealOnlyGestureActive = false,
                directTouch = false,
                phase = StreamTouchPhase.UPDATE,
            ),
        )
        assertFalse(
            ControlRevealGesturePolicy.shouldConsumeActiveRevealOnlyGesture(
                revealOnlyGestureActive = true,
                directTouch = false,
                phase = StreamTouchPhase.UPDATE,
            ),
        )
    }
}
