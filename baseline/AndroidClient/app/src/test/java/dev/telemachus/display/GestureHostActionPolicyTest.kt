package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class GestureHostActionPolicyTest {
    @Test
    fun `default profile preserves existing touch handling`() {
        assertFalse(GestureHostActionPolicy.shouldInterceptThreeFingerGestures(GestureHostActionProfile.DEFAULT))
        assertEquals(
            GestureHostActionDecision.Default,
            GestureHostActionPolicy.resolve(
                trigger = GestureHostActionTrigger.THREE_FINGER_SWIPE_UP,
                profile = GestureHostActionProfile.DEFAULT,
                context = allowedContext(HostActionMenuPolicy.ACTION_MOVE_WINDOW),
            ),
        )
    }

    @Test
    fun defaultChoicesDoNotInterceptThreeFingerGestures() {
        val profile =
            GestureHostActionProfile.fromChoices(
                swipeUp = GestureHostActionChoice.DEFAULT,
                swipeDown = GestureHostActionChoice.DEFAULT,
            )

        assertFalse(GestureHostActionPolicy.shouldInterceptThreeFingerGestures(profile))
    }

    @Test
    fun `explicit three finger host action mapping invokes only available action`() {
        val profile =
            GestureHostActionProfile(
                mappings =
                    listOf(
                        GestureHostActionMapping(
                            trigger = GestureHostActionTrigger.THREE_FINGER_SWIPE_UP,
                            action = GestureHostActionMappingAction.InvokeHostAction(HostActionMenuPolicy.ACTION_MOVE_WINDOW),
                        ),
                    ),
            )

        assertTrue(GestureHostActionPolicy.shouldInterceptThreeFingerGestures(profile))
        assertEquals(
            GestureHostActionDecision.InvokeHostAction(HostActionMenuPolicy.ACTION_MOVE_WINDOW),
            GestureHostActionPolicy.resolve(
                trigger = GestureHostActionTrigger.THREE_FINGER_SWIPE_UP,
                profile = profile,
                context = allowedContext(HostActionMenuPolicy.ACTION_MOVE_WINDOW),
            ),
        )
        assertEquals(
            GestureHostActionDecision.Default,
            GestureHostActionPolicy.resolve(
                trigger = GestureHostActionTrigger.THREE_FINGER_SWIPE_DOWN,
                profile = profile,
                context = allowedContext(HostActionMenuPolicy.ACTION_MOVE_WINDOW),
            ),
        )
    }

    @Test
    fun choiceProfileMapsSavedSettingsToFixedHostActionIds() {
        val profile =
            GestureHostActionProfile.fromChoices(
                swipeUp = GestureHostActionChoice.MOVE_WINDOW,
                swipeDown = GestureHostActionChoice.RETURN_WINDOWS,
            )

        assertTrue(GestureHostActionPolicy.shouldInterceptThreeFingerGestures(profile))
        assertEquals(
            GestureHostActionDecision.InvokeHostAction(HostActionMenuPolicy.ACTION_MOVE_WINDOW),
            GestureHostActionPolicy.resolve(
                trigger = GestureHostActionTrigger.THREE_FINGER_SWIPE_UP,
                profile = profile,
                context = allowedContext(
                    HostActionMenuPolicy.ACTION_MOVE_WINDOW,
                    HostActionMenuPolicy.ACTION_RETURN_WINDOWS,
                ),
            ),
        )
        assertEquals(
            GestureHostActionDecision.InvokeHostAction(HostActionMenuPolicy.ACTION_RETURN_WINDOWS),
            GestureHostActionPolicy.resolve(
                trigger = GestureHostActionTrigger.THREE_FINGER_SWIPE_DOWN,
                profile = profile,
                context = allowedContext(
                    HostActionMenuPolicy.ACTION_MOVE_WINDOW,
                    HostActionMenuPolicy.ACTION_RETURN_WINDOWS,
                ),
            ),
        )
    }

    @Test
    fun savedChoiceFallsBackToDefaultWhenCurrentHostDoesNotAdvertiseTheAction() {
        val returnOnlyHost = listOf(hostAction(HostActionMenuPolicy.ACTION_RETURN_WINDOWS))

        assertEquals(
            GestureHostActionChoice.DEFAULT,
            GestureHostActionChoice.MOVE_WINDOW.effectiveForHostActions(returnOnlyHost),
        )
        assertEquals(
            GestureHostActionChoice.RETURN_WINDOWS,
            GestureHostActionChoice.RETURN_WINDOWS.effectiveForHostActions(returnOnlyHost),
        )
        assertTrue(GestureHostActionChoice.DEFAULT.isSupportedByHostActions(returnOnlyHost))
        assertFalse(GestureHostActionChoice.MOVE_WINDOW.isSupportedByHostActions(returnOnlyHost))
        assertTrue(GestureHostActionChoice.RETURN_WINDOWS.isSupportedByHostActions(returnOnlyHost))
    }

    @Test
    fun unknownHostActionIdFailsClosedEvenWhenAdvertised() {
        val profile =
            GestureHostActionProfile(
                mappings =
                    listOf(
                        GestureHostActionMapping(
                            trigger = GestureHostActionTrigger.THREE_FINGER_SWIPE_UP,
                            action = GestureHostActionMappingAction.InvokeHostAction("custom-action"),
                        ),
                    ),
            )

        assertEquals(
            GestureHostActionDecision.Denied,
            GestureHostActionPolicy.resolve(
                trigger = GestureHostActionTrigger.THREE_FINGER_SWIPE_UP,
                profile = profile,
                context = allowedContext("custom-action"),
            ),
        )
    }

    @Test
    fun `custom gestures and host actions are deny wins independently`() {
        val profile =
            GestureHostActionProfile(
                mappings =
                    listOf(
                        GestureHostActionMapping(
                            trigger = GestureHostActionTrigger.THREE_FINGER_SWIPE_UP,
                            action = GestureHostActionMappingAction.InvokeHostAction(HostActionMenuPolicy.ACTION_MOVE_WINDOW),
                        ),
                    ),
            )
        val deniedContexts =
            listOf(
                allowedContext(HostActionMenuPolicy.ACTION_MOVE_WINDOW).copy(customGesturesAllowed = false),
                allowedContext(HostActionMenuPolicy.ACTION_MOVE_WINDOW).copy(hostActionsAllowed = false),
                allowedContext(HostActionMenuPolicy.ACTION_MOVE_WINDOW).copy(hostActionsNegotiated = false),
                allowedContext(HostActionMenuPolicy.ACTION_MOVE_WINDOW).copy(availableHostActionIds = emptySet()),
            )

        deniedContexts.forEach { context ->
            assertEquals(
                GestureHostActionDecision.Denied,
                GestureHostActionPolicy.resolve(
                    trigger = GestureHostActionTrigger.THREE_FINGER_SWIPE_UP,
                    profile = profile,
                    context = context,
                ),
            )
        }
    }

    @Test
    fun `explicit deny consumes the opted in three finger trigger`() {
        val profile =
            GestureHostActionProfile(
                mappings =
                    listOf(
                        GestureHostActionMapping(
                            trigger = GestureHostActionTrigger.THREE_FINGER_SWIPE_DOWN,
                            action = GestureHostActionMappingAction.Deny,
                        ),
                    ),
            )

        assertTrue(GestureHostActionPolicy.shouldInterceptThreeFingerGestures(profile))
        assertEquals(
            GestureHostActionDecision.Denied,
            GestureHostActionPolicy.resolve(
                trigger = GestureHostActionTrigger.THREE_FINGER_SWIPE_DOWN,
                profile = profile,
                context = allowedContext(HostActionMenuPolicy.ACTION_RETURN_WINDOWS),
            ),
        )
    }

    @Test
    fun `explicit default mapping falls through even when another trigger is intercepted`() {
        val profile =
            GestureHostActionProfile(
                mappings =
                    listOf(
                        GestureHostActionMapping(
                            trigger = GestureHostActionTrigger.THREE_FINGER_SWIPE_UP,
                            action = GestureHostActionMappingAction.Default,
                        ),
                        GestureHostActionMapping(
                            trigger = GestureHostActionTrigger.THREE_FINGER_SWIPE_DOWN,
                            action = GestureHostActionMappingAction.Deny,
                        ),
                    ),
            )

        assertTrue(GestureHostActionPolicy.shouldInterceptThreeFingerGestures(profile))
        assertEquals(
            GestureHostActionDecision.Default,
            GestureHostActionPolicy.resolve(
                trigger = GestureHostActionTrigger.THREE_FINGER_SWIPE_UP,
                profile = profile,
                context = allowedContext(HostActionMenuPolicy.ACTION_MOVE_WINDOW),
            ),
        )
    }

    @Test
    fun `duplicate trigger mappings fail closed`() {
        val profile =
            GestureHostActionProfile(
                mappings =
                    listOf(
                        GestureHostActionMapping(
                            trigger = GestureHostActionTrigger.THREE_FINGER_SWIPE_UP,
                            action = GestureHostActionMappingAction.InvokeHostAction(HostActionMenuPolicy.ACTION_MOVE_WINDOW),
                        ),
                        GestureHostActionMapping(
                            trigger = GestureHostActionTrigger.THREE_FINGER_SWIPE_UP,
                            action = GestureHostActionMappingAction.Deny,
                        ),
                    ),
            )

        assertEquals(
            GestureHostActionDecision.Denied,
            GestureHostActionPolicy.resolve(
                trigger = GestureHostActionTrigger.THREE_FINGER_SWIPE_UP,
                profile = profile,
                context = allowedContext(HostActionMenuPolicy.ACTION_MOVE_WINDOW),
            ),
        )
    }

    @Test
    fun `three finger classifier emits vertical swipes once direction is clear`() {
        val classifier = ThreeFingerGestureClassifier(minimumSwipeFraction = 0.1f)

        assertEquals(null, classifier.consume(sample(phase = ThreeFingerGesturePhase.BEGIN, centroidY = 700f)))
        assertEquals(
            GestureHostActionTrigger.THREE_FINGER_SWIPE_UP,
            classifier.consume(sample(phase = ThreeFingerGesturePhase.MOVE, centroidY = 500f)),
        )
        assertEquals(null, classifier.consume(sample(phase = ThreeFingerGesturePhase.END, centroidY = 450f)))

        assertEquals(null, classifier.consume(sample(phase = ThreeFingerGesturePhase.BEGIN, centroidY = 300f)))
        assertEquals(
            GestureHostActionTrigger.THREE_FINGER_SWIPE_DOWN,
            classifier.consume(sample(phase = ThreeFingerGesturePhase.MOVE, centroidY = 470f)),
        )
    }

    @Test
    fun `three finger classifier emits once when motion crosses swipe threshold`() {
        val classifier = ThreeFingerGestureClassifier(minimumSwipeFraction = 0.1f)

        assertEquals(null, classifier.consume(sample(phase = ThreeFingerGesturePhase.BEGIN, centroidY = 700f)))
        assertEquals(
            GestureHostActionTrigger.THREE_FINGER_SWIPE_UP,
            classifier.consume(sample(phase = ThreeFingerGesturePhase.MOVE, centroidY = 500f)),
        )
        assertEquals(null, classifier.consume(sample(phase = ThreeFingerGesturePhase.MOVE, centroidY = 450f)))
    }

    @Test
    fun `three finger classifier ignores short incomplete and cancelled gestures`() {
        val classifier = ThreeFingerGestureClassifier(minimumSwipeFraction = 0.1f)

        classifier.consume(sample(phase = ThreeFingerGesturePhase.BEGIN, centroidY = 400f))
        assertEquals(null, classifier.consume(sample(phase = ThreeFingerGesturePhase.END, centroidY = 450f)))

        classifier.consume(sample(phase = ThreeFingerGesturePhase.BEGIN, centroidY = 800f))
        classifier.consume(sample(phase = ThreeFingerGesturePhase.CANCEL, centroidY = 100f))
        assertEquals(null, classifier.consume(sample(phase = ThreeFingerGesturePhase.END, centroidY = 100f)))

        classifier.consume(sample(phase = ThreeFingerGesturePhase.BEGIN, centroidY = 800f))
        classifier.consume(sample(phase = ThreeFingerGesturePhase.OTHER, centroidY = 100f))
        assertEquals(null, classifier.consume(sample(phase = ThreeFingerGesturePhase.END, centroidY = 100f)))

        assertEquals(
            null,
            classifier.consume(sample(pointerCount = 2, phase = ThreeFingerGesturePhase.END, centroidY = 100f)),
        )
    }

    private fun allowedContext(vararg actionIds: String) =
        GestureHostActionPolicyContext(
            customGesturesAllowed = true,
            hostActionsAllowed = true,
            hostActionsNegotiated = true,
            availableHostActionIds = actionIds.toSet(),
        )

    private fun hostAction(actionId: String): HostActionOption =
        HostActionOption(id = actionId, name = actionId, requiresConfirmation = false)

    private fun sample(
        pointerCount: Int = 3,
        phase: ThreeFingerGesturePhase,
        centroidY: Float,
        viewportHeight: Int = 1000,
    ) = ThreeFingerGestureSample(
        pointerCount = pointerCount,
        phase = phase,
        centroidY = centroidY,
        viewportHeight = viewportHeight,
    )
}
