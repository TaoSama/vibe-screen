package dev.telemachus.display

import android.net.Uri
import com.google.protobuf.ByteString
import java.io.File
import java.util.concurrent.Executor
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class IncomingFilePublicationCoordinatorTest {
    @Test
    fun inlineExecutorReceivesAnInitializedOperationSubscription() {
        val recovery = recovery("inline")
        val coordinator = coordinator(Executor(Runnable::run), recovery) { Uri.parse("content://downloads/inline") }
        var callbackSubscription: IncomingFilePublicationSubscription? = null

        val returned = coordinator.publish(recovery) { subscription, result ->
            callbackSubscription = subscription
            assertEquals("content://downloads/inline", result.getOrThrow().publication.getOrThrow().toString())
        }

        assertTrue(callbackSubscription === returned)
    }

    @Test
    fun concurrentSubscribersShareOnePublicationAndReceiveTheSameResult() {
        val executor = QueuedExecutor()
        val recovery = recovery("shared")
        var publications = 0
        val coordinator = coordinator(executor, recovery) { publications += 1; Uri.parse("content://downloads/shared") }
        val first = mutableListOf<Result<IncomingFilePublicationResult>>()
        val second = mutableListOf<Result<IncomingFilePublicationResult>>()

        coordinator.publish(recovery) { _, result -> first.add(result) }
        coordinator.publish(recovery) { _, result -> second.add(result) }
        assertEquals(1, executor.pendingCount)

        executor.runNext()

        assertEquals(1, publications)
        assertEquals(
            first.single().getOrThrow().publication.getOrThrow(),
            second.single().getOrThrow().publication.getOrThrow(),
        )
    }

    @Test
    fun closingOldSubscriberDoesNotCancelWorkAndNewSubscriberCanTakeOver() {
        val executor = QueuedExecutor()
        val recovery = recovery("rotate")
        var publications = 0
        val coordinator = coordinator(executor, recovery) { publications += 1; Uri.parse("content://downloads/rotate") }
        val oldResults = mutableListOf<Result<IncomingFilePublicationResult>>()
        val newResults = mutableListOf<Result<IncomingFilePublicationResult>>()

        coordinator.publish(recovery) { _, result -> oldResults.add(result) }.close()
        assertNotNull(coordinator.observeLatest { _, result -> newResults.add(result) })
        executor.runNext()

        assertTrue(oldResults.isEmpty())
        assertEquals(1, publications)
        assertEquals("content://downloads/rotate", newResults.single().getOrThrow().publication.getOrThrow().toString())
    }

    @Test
    fun completedResultRemainsObservableUntilConsumed() {
        val executor = QueuedExecutor()
        val recovery = recovery("completed")
        val coordinator = coordinator(executor, recovery) { Uri.parse("content://downloads/completed") }
        val subscription = coordinator.publish(recovery) { _, _ -> }
        executor.runNext()
        val resumed = mutableListOf<Result<IncomingFilePublicationResult>>()

        assertNotNull(coordinator.observeLatest { _, result -> resumed.add(result) })
        assertEquals("content://downloads/completed", resumed.single().getOrThrow().publication.getOrThrow().toString())
        assertTrue(subscription.consume())
        assertNull(coordinator.observeLatest { _, _ -> })
        assertFalse(subscription.consume())
    }

    @Test
    fun completedOperationObserverReceivesItsReturnedSubscription() {
        val executor = QueuedExecutor()
        val recovery = recovery("completed-subscription")
        val coordinator = coordinator(executor, recovery) { Uri.parse("content://downloads/completed-subscription") }
        coordinator.publish(recovery) { _, _ -> }
        executor.runNext()
        var callbackSubscription: IncomingFilePublicationSubscription? = null

        val returned = coordinator.observe(recovery) { subscription, result ->
            callbackSubscription = subscription
            assertEquals(
                "content://downloads/completed-subscription",
                result.getOrThrow().publication.getOrThrow().toString(),
            )
        }

        assertNotNull(returned)
        assertTrue(callbackSubscription === returned)
    }

    @Test
    fun publicationCompletesWithoutAnAttachedObserver() {
        val executor = QueuedExecutor()
        val recovery = recovery("detached")
        var publications = 0
        val coordinator = coordinator(executor, recovery) { publications += 1; Uri.parse("content://downloads/detached") }

        val subscription = coordinator.publish(recovery) { _, _ -> }
        subscription.close()
        executor.runNext()
        val resumed = mutableListOf<Result<IncomingFilePublicationResult>>()

        assertEquals(1, publications)
        assertNotNull(coordinator.observeLatest { _, result -> resumed.add(result) })
        assertEquals("content://downloads/detached", resumed.single().getOrThrow().publication.getOrThrow().toString())
    }

    @Test
    fun failureSurvivesObserverReplacementAndCanBeConsumedForRetry() {
        val executor = QueuedExecutor()
        val recovery = recovery("failure")
        val expected = IllegalStateException("publication failed")
        val coordinator = coordinator(executor, recovery) { throw expected }
        val subscription = coordinator.publish(recovery) { _, _ -> }
        subscription.close()
        executor.runNext()
        val resumed = mutableListOf<Result<IncomingFilePublicationResult>>()

        assertNotNull(coordinator.observe(recovery) { _, result -> resumed.add(result) })
        assertEquals(expected, resumed.single().getOrThrow().publication.exceptionOrNull())
        assertTrue(subscription.consume())
    }

    @Test
    fun recoveryLoadFailureCanBeConsumedBeforeAReplacementAttempt() {
        val executor = QueuedExecutor()
        val recovery = recovery("load-failure")
        val expected = IllegalStateException("load failed")
        var loadFailure: Throwable? = expected
        val coordinator =
            IncomingFilePublicationCoordinator(
                executor = executor,
                loadRecovery = { loadFailure?.let { throw it }; recovery },
                publishRecovery = { Uri.parse("content://downloads/load-failure") },
            )
        val first = mutableListOf<Result<IncomingFilePublicationResult>>()
        val subscription = coordinator.publish(recovery) { _, result -> first.add(result) }
        executor.runNext()

        assertEquals(expected, first.single().exceptionOrNull())
        assertTrue(subscription.consume())
        loadFailure = null
        val retried = mutableListOf<Result<IncomingFilePublicationResult>>()
        coordinator.publish(recovery) { _, result -> retried.add(result) }
        executor.runNext()
        assertEquals("content://downloads/load-failure", retried.single().getOrThrow().publication.getOrThrow().toString())
    }

    @Test
    fun staleSubscriptionCannotConsumeANewerOperation() {
        val executor = QueuedExecutor()
        var current = recovery("old")
        val coordinator =
            IncomingFilePublicationCoordinator(
                executor = executor,
                loadRecovery = { current },
                publishRecovery = { Uri.parse("content://downloads/${it.recoveryId}") },
            )
        val oldSubscription = coordinator.publish(current) { _, _ -> }
        executor.runNext()
        current = recovery("new")
        val newResults = mutableListOf<Result<IncomingFilePublicationResult>>()
        coordinator.publish(current) { _, result -> newResults.add(result) }

        assertFalse(oldSubscription.consume())
        executor.runNext()
        assertEquals("content://downloads/new", newResults.single().getOrThrow().publication.getOrThrow().toString())
    }

    private fun coordinator(
        executor: Executor,
        recovery: RecoveredIncomingFile,
        publish: (RecoveredIncomingFile) -> Uri,
    ) = IncomingFilePublicationCoordinator(executor, { recovery }, publish)

    private fun recovery(id: String): RecoveredIncomingFile {
        val transferId = ByteString.copyFromUtf8("transfer-$id")
        val digest = ByteString.copyFrom(ByteArray(32) { it.toByte() })
        return RecoveredIncomingFile(
            recoveryId = id,
            transferId = transferId,
            displayName = "$id.txt",
            mimeType = "text/plain",
            byteLength = 1L,
            sha256 = digest,
            payloadFile = File("/tmp/$id.txt"),
        )
    }

    private class QueuedExecutor : Executor {
        private val tasks = ArrayDeque<Runnable>()
        val pendingCount: Int get() = tasks.size

        override fun execute(command: Runnable) {
            tasks.addLast(command)
        }

        fun runNext() {
            tasks.removeFirst().run()
        }
    }
}
