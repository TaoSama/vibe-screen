package dev.telemachus.display.transport

import java.io.BufferedInputStream
import java.io.DataInputStream
import java.io.DataOutputStream
import java.io.InputStream
import java.io.OutputStream
import java.net.Socket
import java.util.concurrent.atomic.AtomicBoolean

interface StreamTransportConnection {
    val input: DataInputStream

    val output: DataOutputStream

    var readTimeoutMillis: Int

    fun shutdownOutput(): Exception?

    fun closeOnce(): List<Exception>
}

class SocketStreamTransportConnection(
    val socket: Socket,
) : StreamTransportConnection {
    private val stateLock = Any()
    private val closed = AtomicBoolean()
    private val outputShutdown = AtomicBoolean()
    private var installedInput: DataInputStream? = null
    private var installedOutput: DataOutputStream? = null

    override val input: DataInputStream
        get() = synchronized(stateLock) { checkNotNull(installedInput) { "Transport input is not installed" } }

    override val output: DataOutputStream
        get() = synchronized(stateLock) { checkNotNull(installedOutput) { "Transport output is not installed" } }

    override var readTimeoutMillis: Int
        get() = socket.soTimeout
        set(value) {
            socket.soTimeout = value
        }

    fun installStreams(
        rawInput: InputStream = socket.getInputStream(),
        rawOutput: OutputStream = socket.getOutputStream(),
    ) {
        synchronized(stateLock) {
            check(!closed.get()) { "Transport is already closed" }
            check(installedInput == null && installedOutput == null) { "Transport streams are already installed" }
            installedInput = DataInputStream(BufferedInputStream(rawInput, STREAM_BUFFER_BYTES))
            installedOutput = DataOutputStream(rawOutput)
        }
    }

    override fun shutdownOutput(): Exception? {
        if (closed.get() || !outputShutdown.compareAndSet(false, true)) return null
        return try {
            socket.shutdownOutput()
            null
        } catch (failure: Exception) {
            failure
        }
    }

    override fun closeOnce(): List<Exception> {
        if (!closed.compareAndSet(false, true)) return emptyList()
        return try {
            socket.close()
            emptyList()
        } catch (failure: Exception) {
            listOf(failure)
        }
    }

    private companion object {
        private const val STREAM_BUFFER_BYTES = 65_536
    }
}

class StreamTransportCandidate<C : StreamTransportConnection> internal constructor(
    val connection: C,
    val attemptGeneration: Long,
)

enum class StreamTransportCandidateRejection {
    INELIGIBLE,
    PENDING_EXISTS,
}

class StreamTransportCandidateRejectedException(
    val reason: StreamTransportCandidateRejection,
    val closeFailures: List<Exception>,
) : IllegalStateException("Transport candidate rejected: $reason")

data class StreamTransportPromotion(
    val promoted: Boolean,
    val closeFailures: List<Exception>,
)

class StreamTransportOwner<C : StreamTransportConnection> {
    private val lock = Any()
    private var active: C? = null
    private var pending: StreamTransportCandidate<C>? = null

    fun activeConnection(): StreamTransportConnection? = synchronized(lock) { active }

    fun createCandidate(
        attemptGeneration: Long,
        eligible: (Long) -> Boolean,
        connectionFactory: () -> C,
    ): StreamTransportCandidate<C> =
        synchronized(lock) {
            if (!eligible(attemptGeneration)) {
                throw StreamTransportCandidateRejectedException(
                    StreamTransportCandidateRejection.INELIGIBLE,
                    emptyList(),
                )
            }
            if (pending != null) {
                throw StreamTransportCandidateRejectedException(
                    StreamTransportCandidateRejection.PENDING_EXISTS,
                    emptyList(),
                )
            }
            val connection = connectionFactory()
            if (!eligible(attemptGeneration)) {
                throw StreamTransportCandidateRejectedException(
                    StreamTransportCandidateRejection.INELIGIBLE,
                    connection.closeOnce(),
                )
            }
            StreamTransportCandidate(connection, attemptGeneration).also { pending = it }
        }

    fun promote(
        candidate: StreamTransportCandidate<C>,
        acceptsGeneration: (Long) -> Boolean,
    ): StreamTransportPromotion {
        var replacedActive: C? = null
        val promoted =
            synchronized(lock) {
                if (pending !== candidate || !acceptsGeneration(candidate.attemptGeneration)) {
                    if (pending === candidate) pending = null
                    false
                } else {
                    pending = null
                    replacedActive = active
                    active = candidate.connection
                    true
                }
            }
        val failures =
            if (promoted) {
                replacedActive?.closeOnce().orEmpty()
            } else {
                candidate.connection.closeOnce()
            }
        return StreamTransportPromotion(promoted, failures)
    }

    fun release(candidate: StreamTransportCandidate<C>): List<Exception> {
        synchronized(lock) {
            if (pending === candidate) pending = null
        }
        return candidate.connection.closeOnce()
    }

    fun closeActive(): List<Exception> {
        val connection = synchronized(lock) { active.also { active = null } }
        return connection?.closeOnce().orEmpty()
    }

    fun closeAll(): List<Exception> {
        val connections =
            synchronized(lock) {
                listOfNotNull(active, pending?.connection).also {
                    active = null
                    pending = null
                }
            }
        val uniqueConnections = java.util.Collections.newSetFromMap(
            java.util.IdentityHashMap<C, Boolean>(),
        )
        return connections
            .filter(uniqueConnections::add)
            .flatMap { it.closeOnce() }
    }

    fun shutdownActiveOutput(): Exception? = activeConnection()?.shutdownOutput()
}
