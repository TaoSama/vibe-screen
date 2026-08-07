package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ActiveDecoderCallbackBindingTest {
    @Test
    fun decoderAOldCallbackCannotAffectActiveDecoderB() {
        val decoderA = Any()
        val decoderB = Any()
        var activeDecoder: Any? = decoderA
        var sessionGeneration = 7L
        var fallbackRequests = 0
        val bindingA =
            ActiveDecoderCallbackBinding(decoderA, sessionGeneration) { decoder, generation ->
                generation == sessionGeneration && decoder === activeDecoder
            }
        val bindingB =
            ActiveDecoderCallbackBinding(decoderB, sessionGeneration) { decoder, generation ->
                generation == sessionGeneration && decoder === activeDecoder
            }

        assertTrue(bindingA.runIfActive { fallbackRequests++ })
        activeDecoder = decoderB
        assertFalse(bindingA.runIfActive { fallbackRequests++ })
        assertTrue(bindingB.runIfActive { fallbackRequests++ })
        sessionGeneration++
        assertFalse(bindingA.runIfActive { fallbackRequests++ })
        assertFalse(bindingB.runIfActive { fallbackRequests++ })

        assertEquals(2, fallbackRequests)
    }
}
