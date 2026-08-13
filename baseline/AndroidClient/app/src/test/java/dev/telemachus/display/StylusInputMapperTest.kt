package dev.telemachus.display

import android.view.MotionEvent
import dev.vibescreen.protocol.v1.InputPhase
import dev.telemachus.display.protocol.MotionActions
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.PI

class StylusInputMapperTest {
    @Test
    fun `maps lifecycle and zeros terminal pressure`() {
        val pointer = pointer(pressure = 0.8)
        assertEquals(InputPhase.INPUT_PHASE_BEGAN, map(MotionActions.DOWN, pointer).single().phase)
        assertEquals(0.8, map(MotionActions.MOVE, pointer).single().pressure, 0.0)
        assertEquals(0.0, map(MotionActions.UP, pointer).single().pressure, 0.0)
        assertEquals(0.0, map(MotionActions.CANCEL, pointer).single().pressure, 0.0)
    }

    @Test
    fun `orientation maps tilt toward four screen directions`() {
        val magnitude = PI / 4.0
        val samples =
            listOf(
                sample(pointer(tilt = magnitude, orientation = 0.0)),
                sample(pointer(tilt = magnitude, orientation = PI / 2.0)),
                sample(pointer(tilt = magnitude, orientation = PI)),
                sample(pointer(tilt = magnitude, orientation = -PI / 2.0)),
            )
        assertTilt(samples[0], 0.0, -45.0)
        assertTilt(samples[1], 45.0, 0.0)
        assertTilt(samples[2], 0.0, 45.0)
        assertTilt(samples[3], -45.0, 0.0)
        samples.forEach { assertTrue(Math.hypot(it.tiltXDegrees, it.tiltYDegrees) <= 90.0) }
    }

    @Test
    fun `filters non stylus and clamps finite axes`() {
        assertTrue(map(MotionActions.DOWN, pointer(isStylus = false)).isEmpty())
        val sample = sample(pointer(x = -2.0, y = 4.0, pressure = 3.0, tilt = PI))
        assertEquals(0.0, sample.x, 0.0)
        assertEquals(1.0, sample.y, 0.0)
        assertEquals(1.0, sample.pressure, 0.0)
        assertEquals(90.0, Math.hypot(sample.tiltXDegrees, sample.tiltYDegrees), 1e-9)
        assertTrue(map(MotionActions.DOWN, pointer(x = Double.NaN)).isEmpty())
    }

    @Test
    fun `move preserves historical samples before current sample`() {
        val samples =
            StylusInputMapper.map(
                StylusMotionSnapshot(
                    MotionActions.MOVE,
                    0,
                    pointers = listOf(pointer(x = 0.3, pressure = 0.3)),
                    historicalPointers =
                        listOf(
                            listOf(pointer(x = 0.1, pressure = 0.1)),
                            listOf(pointer(x = 0.2, pressure = 0.2)),
                        ),
                ),
            )
        assertEquals(listOf(0.1, 0.2, 0.3), samples.map { it.x })
        assertEquals(listOf(0.1, 0.2, 0.3), samples.map { it.pressure })
    }

    @Test
    fun `stylus first gesture stays stylus after stylus lifts before finger`() {
        val stylus = pointer(pointerId = 7)
        val finger = pointer(pointerId = 8, isStylus = false)
        val snapshots =
            listOf(
                StylusMotionSnapshot(MotionActions.DOWN, 0, listOf(stylus)),
                StylusMotionSnapshot(MotionActions.POINTER_DOWN, 1, listOf(stylus, finger)),
                StylusMotionSnapshot(MotionActions.POINTER_UP, 0, listOf(stylus, finger)),
                StylusMotionSnapshot(MotionActions.MOVE, 0, listOf(finger)),
                StylusMotionSnapshot(MotionActions.UP, 0, listOf(finger)),
            )
        listOf(StylusGestureRouter(), StylusGestureRouter()).forEach { router ->
            snapshots.forEach { assertTrue(router.routesToStylus(it, stylusNegotiated = true)) }
            assertTrue(!router.routesToStylus(snapshots[3], stylusNegotiated = true))
        }
    }

    @Test
    fun `finger first gesture stays touch when stylus joins until final up`() {
        val stylus = pointer(pointerId = 7)
        val finger = pointer(pointerId = 8, isStylus = false)
        val snapshots =
            listOf(
                StylusMotionSnapshot(MotionActions.DOWN, 0, listOf(finger)),
                StylusMotionSnapshot(MotionActions.POINTER_DOWN, 1, listOf(finger, stylus)),
                StylusMotionSnapshot(MotionActions.MOVE, 0, listOf(finger, stylus)),
                StylusMotionSnapshot(MotionActions.POINTER_UP, 1, listOf(finger, stylus)),
                StylusMotionSnapshot(MotionActions.UP, 0, listOf(finger)),
            )
        listOf(StylusGestureRouter(), StylusGestureRouter()).forEach { router ->
            snapshots.forEach { assertTrue(!router.routesToStylus(it, stylusNegotiated = true)) }
        }
    }

    @Test
    fun `stylus input tracker clears terminal gesture`() {
        val tracker = StylusInputIdTracker(generateSequence(100L) { it + 1 }.iterator()::next)
        val began = map(MotionActions.DOWN, pointer()).single()
        assertEquals(100L, tracker.resolve(began))
        val cancelled = map(MotionActions.CANCEL, pointer()).single()
        assertEquals(100L, tracker.resolve(cancelled))
        tracker.complete(cancelled)
        assertEquals(0, tracker.activeCount)
    }

    @Test
    fun `extended hover maps proximity lifecycle with zero pressure`() {
        val pen = pointer(pressure = 0.7)
        val phases =
            listOf(MotionEvent.ACTION_HOVER_ENTER, MotionEvent.ACTION_HOVER_MOVE, MotionEvent.ACTION_HOVER_EXIT)
                .map { action -> map(action, pen, extended = true).single() }
        assertEquals(
            listOf(InputPhase.INPUT_PHASE_BEGAN, InputPhase.INPUT_PHASE_CHANGED, InputPhase.INPUT_PHASE_ENDED),
            phases.map { it.phase },
        )
        assertTrue(phases.all { it.contactState == StylusContactState.PROXIMITY && it.pressure == 0.0 })
    }

    @Test
    fun `extended eraser and barrel buttons are preserved`() {
        val sample =
            map(
                MotionActions.MOVE,
                pointer(
                    toolKind = StylusToolKind.ERASER,
                    buttonMask = STYLUS_PRIMARY_BUTTON or STYLUS_SECONDARY_BUTTON,
                ),
                extended = true,
            ).single()
        assertEquals(StylusToolKind.ERASER, sample.toolKind)
        assertEquals(STYLUS_PRIMARY_BUTTON or STYLUS_SECONDARY_BUTTON, sample.buttonMask)
    }

    @Test
    fun `button routing uses pointer lifecycle state rather than pressure`() {
        val router = StylusContactRouter()
        router.map(snapshot(MotionEvent.ACTION_HOVER_ENTER, pointer(pressure = 0.8)), true)
        val hoverButton =
            router.map(
                snapshot(MotionEvent.ACTION_BUTTON_PRESS, pointer(pressure = 0.8, buttonMask = STYLUS_PRIMARY_BUTTON)),
                true,
            ).single()
        assertEquals(StylusContactState.PROXIMITY, hoverButton.contactState)
        assertEquals(0.0, hoverButton.pressure, 0.0)
        assertEquals(StylusDelivery.STRUCTURAL, hoverButton.delivery)

        router.reset()
        router.map(snapshot(MotionActions.DOWN, pointer(pressure = 0.0)), true)
        val contactButton =
            router.map(
                snapshot(MotionEvent.ACTION_BUTTON_RELEASE, pointer(pressure = 0.0)),
                true,
            ).single()
        assertEquals(StylusContactState.CONTACT, contactButton.contactState)
        assertEquals(StylusDelivery.STRUCTURAL, contactButton.delivery)
    }

    @Test
    fun `legacy peer receives only pen contact without buttons`() {
        assertTrue(map(MotionEvent.ACTION_HOVER_MOVE, pointer()).isEmpty())
        assertTrue(map(MotionActions.DOWN, pointer(toolKind = StylusToolKind.ERASER)).isEmpty())
        val sample = map(MotionActions.DOWN, pointer(buttonMask = STYLUS_PRIMARY_BUTTON)).single()
        assertEquals(StylusToolKind.PEN, sample.toolKind)
        assertEquals(StylusContactState.CONTACT, sample.contactState)
        assertEquals(0, sample.buttonMask)
    }

    @Test
    fun `cancel terminates extended contact and clears tracker`() {
        val tracker = StylusInputIdTracker { 700L }
        val began = map(MotionActions.DOWN, pointer(), extended = true).single()
        assertEquals(700L, tracker.resolve(began))
        val cancelled = map(MotionActions.CANCEL, pointer(), extended = true).single()
        assertEquals(700L, tracker.resolve(cancelled))
        tracker.complete(cancelled)
        assertEquals(InputPhase.INPUT_PHASE_CANCELLED, cancelled.phase)
        assertEquals(0, tracker.activeCount)
    }

    @Test
    fun `release boundary drains active proximity as structural cancellation`() {
        val tracker = StylusInputIdTracker { 701L }
        val hover = map(MotionEvent.ACTION_HOVER_ENTER, pointer(), extended = true).single()
        tracker.resolve(hover)

        val cancellation = tracker.takeCancellations().single()
        assertEquals(701L, cancellation.inputId)
        assertEquals(InputPhase.INPUT_PHASE_CANCELLED, cancellation.sample.phase)
        assertEquals(StylusContactState.PROXIMITY, cancellation.sample.contactState)
        assertEquals(StylusDelivery.STRUCTURAL, cancellation.sample.delivery)
        assertEquals(0.0, cancellation.sample.pressure, 0.0)
        assertEquals(0, tracker.activeCount)
    }

    @Test
    fun `stylus release coordinator submits both routes before teardown`() {
        val stream = StylusInputIdTracker { 1L }
        val internet = StylusInputIdTracker { 2L }
        stream.resolve(map(MotionActions.DOWN, pointer(), extended = true).single())
        internet.resolve(map(MotionEvent.ACTION_HOVER_ENTER, pointer(), extended = true).single())
        val events = mutableListOf<String>()

        StylusReleaseCoordinator(stream, internet).completeBoundary(
            submitStream = { events += "stream:${it.single().phase}" },
            submitInternet = { events += "internet:${it.single().sample.phase}" },
            afterRelease = { events += "teardown" },
        )

        assertEquals(
            listOf(
                "stream:INPUT_PHASE_CANCELLED",
                "internet:INPUT_PHASE_CANCELLED",
                "teardown",
            ),
            events,
        )
    }

    private fun map(
        action: Int,
        pointer: StylusPointerSnapshot,
        extended: Boolean = false,
    ) = StylusInputMapper.map(StylusMotionSnapshot(action, 0, listOf(pointer)), extended)

    private fun snapshot(action: Int, pointer: StylusPointerSnapshot) =
        StylusMotionSnapshot(action, 0, listOf(pointer))

    private fun sample(pointer: StylusPointerSnapshot) = map(MotionActions.MOVE, pointer).single()

    private fun pointer(
        pointerId: Int = 7,
        x: Double = 0.25,
        y: Double = 0.75,
        pressure: Double = 0.5,
        tilt: Double = 0.0,
        orientation: Double = 0.0,
        isStylus: Boolean = true,
        toolKind: StylusToolKind? = if (isStylus) StylusToolKind.PEN else null,
        buttonMask: Int = 0,
    ) =
        StylusPointerSnapshot(
            pointerId,
            x,
            y,
            pressure,
            tilt,
            orientation,
            toolKind,
            buttonMask,
        )

    private fun assertTilt(sample: StylusSample, x: Double, y: Double) {
        assertEquals(x, sample.tiltXDegrees, 1e-9)
        assertEquals(y, sample.tiltYDegrees, 1e-9)
    }
}
