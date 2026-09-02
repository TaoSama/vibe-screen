package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Test

class SessionInputIdSequenceTest {
    @Test
    fun inputTypesShareOneStrictlyIncreasingSessionNamespace() {
        val sequence = SessionInputIdSequence()

        val touchInputId = sequence.next()
        val stylusInputId = sequence.next()
        val controllerInputId = sequence.next()

        assertEquals(listOf(1L, 2L, 3L), listOf(touchInputId, stylusInputId, controllerInputId))
    }

    @Test
    fun newNegotiatedSessionRestartsTheNamespace() {
        val sequence = SessionInputIdSequence()
        sequence.next()
        sequence.next()

        sequence.resetForNewSession()

        assertEquals(1L, sequence.next())
    }
}
