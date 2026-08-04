package dev.telemachus.display.protocol

import dev.telemachus.display.protocol.TouchEventBuffer.OfferResult
import dev.vibescreen.protocol.v1.InputPhase
import org.junit.Assert.assertEquals
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class TouchEventPrimitivesTest {
    @Test
    fun `pointer down and up emit only action pointer with its real id`() {
        val pointers =
            listOf(
                MotionPointer(pointerId = 3, x = 0.1, y = 0.2),
                MotionPointer(pointerId = 17, x = 0.7, y = 0.8),
            )

        assertEquals(
            listOf(TouchSample(17, InputPhase.INPUT_PHASE_BEGAN, 0.7, 0.8)),
            TouchSampleMapper.map(MotionSnapshot(MotionActions.POINTER_DOWN, 1, pointers)),
        )
        assertEquals(
            listOf(TouchSample(3, InputPhase.INPUT_PHASE_ENDED, 0.1, 0.2)),
            TouchSampleMapper.map(MotionSnapshot(MotionActions.POINTER_UP, 0, pointers)),
        )
        assertEquals(
            listOf(TouchSample(3, InputPhase.INPUT_PHASE_BEGAN, 0.1, 0.2)),
            TouchSampleMapper.map(MotionSnapshot(MotionActions.DOWN, 0, pointers.take(1))),
        )
        assertEquals(
            listOf(TouchSample(3, InputPhase.INPUT_PHASE_ENDED, 0.1, 0.2)),
            TouchSampleMapper.map(MotionSnapshot(MotionActions.UP, 0, pointers.take(1))),
        )
    }

    @Test
    fun `move and cancel emit every active pointer with distinct phases`() {
        val pointers =
            listOf(
                MotionPointer(pointerId = 9, x = 0.25, y = 0.5),
                MotionPointer(pointerId = 42, x = 0.75, y = 1.0),
            )

        assertEquals(
            listOf(
                TouchSample(9, InputPhase.INPUT_PHASE_CHANGED, 0.25, 0.5),
                TouchSample(42, InputPhase.INPUT_PHASE_CHANGED, 0.75, 1.0),
            ),
            TouchSampleMapper.map(MotionSnapshot(MotionActions.MOVE, 0, pointers)),
        )
        assertEquals(
            listOf(
                TouchSample(9, InputPhase.INPUT_PHASE_CANCELLED, 0.25, 0.5),
                TouchSample(42, InputPhase.INPUT_PHASE_CANCELLED, 0.75, 1.0),
            ),
            TouchSampleMapper.map(MotionSnapshot(MotionActions.CANCEL, 0, pointers)),
        )
    }

    @Test
    fun `boundary outside forwarded pointer range is ignored`() {
        val forwarded = listOf(MotionPointer(pointerId = 3, x = 0.1, y = 0.2), MotionPointer(17, 0.7, 0.8))

        assertEquals(
            emptyList<TouchSample>(),
            TouchSampleMapper.map(MotionSnapshot(MotionActions.POINTER_DOWN, actionIndex = 2, forwarded)),
        )
        assertEquals(
            emptyList<TouchSample>(),
            TouchSampleMapper.map(MotionSnapshot(MotionActions.POINTER_UP, actionIndex = 2, forwarded)),
        )
    }

    @Test
    fun `move storm stays bounded and retains latest coordinate`() {
        val buffer = TouchEventBuffer(capacity = 4)
        assertEquals(OfferResult.ACCEPTED, buffer.offer(sample(7, InputPhase.INPUT_PHASE_BEGAN, 0.0)))
        repeat(10_000) { index ->
            assertEquals(
                OfferResult.ACCEPTED,
                buffer.offer(sample(7, InputPhase.INPUT_PHASE_CHANGED, index / 10_000.0)),
            )
        }
        assertEquals(OfferResult.ACCEPTED, buffer.offer(sample(7, InputPhase.INPUT_PHASE_ENDED, 1.0)))

        assertEquals(3, buffer.size())
        assertEquals(InputPhase.INPUT_PHASE_BEGAN, buffer.take().phase)
        assertEquals(0.9999, buffer.take().x, 0.0)
        assertEquals(InputPhase.INPUT_PHASE_ENDED, buffer.take().phase)
    }

    @Test
    fun `boundaries remain ordered when a full buffer evicts motion`() {
        val buffer = TouchEventBuffer(capacity = 4)
        buffer.offer(sample(1, InputPhase.INPUT_PHASE_BEGAN, 0.0))
        buffer.offer(sample(1, InputPhase.INPUT_PHASE_CHANGED, 0.2))
        buffer.offer(sample(2, InputPhase.INPUT_PHASE_BEGAN, 0.3))
        buffer.offer(sample(2, InputPhase.INPUT_PHASE_CHANGED, 0.4))

        assertEquals(OfferResult.ACCEPTED, buffer.offer(sample(1, InputPhase.INPUT_PHASE_ENDED, 0.5)))

        val drained = List(4) { buffer.take() }
        assertEquals(
            listOf(
                1 to InputPhase.INPUT_PHASE_BEGAN,
                1 to InputPhase.INPUT_PHASE_CHANGED,
                2 to InputPhase.INPUT_PHASE_BEGAN,
                1 to InputPhase.INPUT_PHASE_ENDED,
            ),
            drained.map { it.pointerId to it.phase },
        )
    }

    @Test
    fun `ended retries instead of evicting final move for same pointer`() {
        val buffer = TouchEventBuffer(capacity = 3)
        buffer.offer(sample(1, InputPhase.INPUT_PHASE_BEGAN, 0.0))
        buffer.offer(sample(1, InputPhase.INPUT_PHASE_CHANGED, 0.8))
        buffer.offer(sample(2, InputPhase.INPUT_PHASE_BEGAN, 0.2))
        val ended = sample(1, InputPhase.INPUT_PHASE_ENDED, 0.9)

        assertEquals(OfferResult.RETRY_REQUIRED, buffer.offer(ended))
        assertEquals(InputPhase.INPUT_PHASE_BEGAN, buffer.take().phase)
        assertEquals(OfferResult.ACCEPTED, buffer.offer(ended))

        val finalMove = buffer.take()
        assertEquals(InputPhase.INPUT_PHASE_CHANGED, finalMove.phase)
        assertEquals(0.8, finalMove.x, 0.0)
        assertEquals(2, buffer.take().pointerId)
        assertEquals(InputPhase.INPUT_PHASE_ENDED, buffer.take().phase)
    }

    @Test
    fun `full boundary-only buffer requires retry`() {
        val buffer = TouchEventBuffer(capacity = 2)
        buffer.offer(sample(1, InputPhase.INPUT_PHASE_BEGAN, 0.0))
        buffer.offer(sample(2, InputPhase.INPUT_PHASE_BEGAN, 0.1))

        assertEquals(OfferResult.RETRY_REQUIRED, buffer.offer(sample(1, InputPhase.INPUT_PHASE_ENDED, 0.2)))
        assertEquals(2, buffer.size())
    }

    @Test
    fun `blocking put preserves boundary until bounded buffer has space`() {
        val buffer = TouchEventBuffer(capacity = 1)
        buffer.offer(sample(1, InputPhase.INPUT_PHASE_BEGAN, 0.0))
        val completed = CountDownLatch(1)
        val producer =
            Thread {
                buffer.put(sample(1, InputPhase.INPUT_PHASE_ENDED, 1.0))
                completed.countDown()
            }.apply { start() }

        assertEquals(false, completed.await(100, TimeUnit.MILLISECONDS))
        assertEquals(InputPhase.INPUT_PHASE_BEGAN, buffer.take().phase)
        assertEquals(true, completed.await(1, TimeUnit.SECONDS))
        assertEquals(InputPhase.INPUT_PHASE_ENDED, buffer.take().phase)
        producer.join(1_000)
    }

    @Test
    fun `changed does not coalesce across pointer boundary`() {
        val buffer = TouchEventBuffer(capacity = 4)
        buffer.offer(sample(5, InputPhase.INPUT_PHASE_CHANGED, 0.1))
        buffer.offer(sample(5, InputPhase.INPUT_PHASE_ENDED, 0.2))
        buffer.offer(sample(5, InputPhase.INPUT_PHASE_CHANGED, 0.3))

        assertEquals(3, buffer.size())
        assertEquals(0.1, buffer.take().x, 0.0)
        assertEquals(InputPhase.INPUT_PHASE_ENDED, buffer.take().phase)
        assertEquals(0.3, buffer.take().x, 0.0)
    }

    private fun sample(
        pointerId: Int,
        phase: InputPhase,
        x: Double,
    ) = TouchSample(pointerId, phase, x, x)
}
