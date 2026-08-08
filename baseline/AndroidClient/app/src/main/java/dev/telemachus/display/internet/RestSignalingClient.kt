package dev.telemachus.display.internet

import com.google.gson.Gson
import com.google.gson.JsonParseException
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL
import java.nio.charset.StandardCharsets
import java.util.UUID
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import kotlin.math.min

/** Production client for the signaling service's authenticated REST long-poll API. */
class RestSignalingClient(
    private val configuration: SignalingConfiguration,
    sessionId: String,
    private val gson: Gson = Gson(),
) : SignalingClient {
    private val sessionUrl =
        try {
            buildSessionUrl(configuration.baseUrl, sessionId)
        } catch (failure: Throwable) {
            configuration.close()
            throw failure
        }
    private val closed = AtomicBoolean(false)
    private val started = AtomicBoolean(false)
    private val activePoll = AtomicReference<HttpURLConnection?>()
    private val pollExecutor = namedSingleThreadExecutor("vibe-signaling-poll")
    private val sendExecutor = namedSingleThreadExecutor("vibe-signaling-send")
    private lateinit var listener: SignalingClient.Listener

    override fun start(listener: SignalingClient.Listener) {
        check(started.compareAndSet(false, true)) { "Signaling client has already started" }
        check(!closed.get()) { "Signaling client is closed" }
        this.listener = listener
        pollExecutor.execute(::pollLoop)
    }

    override fun sendOffer(sdp: String) = enqueue(SignalingMessage(type = TYPE_OFFER, sdp = requireSdp(sdp)))

    override fun sendAnswer(sdp: String) = enqueue(SignalingMessage(type = TYPE_ANSWER, sdp = requireSdp(sdp)))

    override fun sendIceCandidate(candidate: SignalingIceCandidate) =
        enqueue(
            SignalingMessage(
                type = TYPE_ICE_CANDIDATE,
                candidate =
                    CandidatePayload(
                        candidate = candidate.candidate,
                        sdp_mid = candidate.sdpMid,
                        sdp_mline_index = candidate.sdpMLineIndex,
                        username_fragment = candidate.usernameFragment,
                    ),
            ),
        )

    override fun sendEndOfCandidates() = enqueue(SignalingMessage(type = TYPE_END_OF_CANDIDATES))

    override fun close() {
        if (!closed.compareAndSet(false, true)) return
        activePoll.getAndSet(null)?.disconnect()
        pollExecutor.shutdownNow()
        sendExecutor.shutdownNow()
        configuration.close()
    }

    private fun enqueue(message: SignalingMessage) {
        check(started.get()) { "Signaling client is not started" }
        check(!closed.get()) { "Signaling client is closed" }
        val identified = message.copy(message_id = UUID.randomUUID().toString())
        sendExecutor.execute {
            try {
                postMessageWithRetry(identified)
            } catch (failure: Throwable) {
                reportFailure(failure)
            }
        }
    }

    private fun pollLoop() {
        var cursor = 0L
        var consecutiveFailures = 0
        while (!closed.get()) {
            try {
                val response = poll(cursor)
                consecutiveFailures = 0
                response.events.orEmpty().forEach(::dispatch)
                cursor = checkNotNull(response.next_cursor)
            } catch (interrupted: InterruptedException) {
                Thread.currentThread().interrupt()
                return
            } catch (failure: Throwable) {
                if (closed.get()) return
                consecutiveFailures++
                if (consecutiveFailures >= MAX_CONSECUTIVE_POLL_FAILURES) {
                    reportFailure(failure)
                    return
                }
                Thread.sleep(min(MAX_RETRY_DELAY_MS, INITIAL_RETRY_DELAY_MS shl (consecutiveFailures - 1)).toLong())
            }
        }
    }

    private fun poll(cursor: Long): EventsResponse {
        val url =
            URL(
                "$sessionUrl/events?after=$cursor&wait_seconds=${configuration.pollWaitSeconds}",
            )
        val connection = open(url, "GET")
        activePoll.set(connection)
        return try {
            val body = connection.readSuccessfulBody()
            val response =
                gson.fromJson(body, EventsResponse::class.java)
                    ?: throw IOException("Signaling returned an empty events document")
            validateEventsResponse(response, cursor)
            response
        } catch (parseFailure: JsonParseException) {
            throw IOException("Signaling returned malformed events JSON", parseFailure)
        } finally {
            activePoll.compareAndSet(connection, null)
            connection.disconnect()
        }
    }

    private fun postMessageWithRetry(message: SignalingMessage) {
        var lastFailure: IOException? = null
        repeat(MAX_POST_ATTEMPTS) { attempt ->
            try {
                postMessage(message)
                return
            } catch (failure: IOException) {
                if (!failure.isRetryable() || closed.get()) throw failure
                lastFailure = failure
                if (attempt + 1 < MAX_POST_ATTEMPTS) {
                    Thread.sleep(min(MAX_RETRY_DELAY_MS, INITIAL_RETRY_DELAY_MS shl attempt).toLong())
                }
            }
        }
        throw checkNotNull(lastFailure)
    }

    private fun postMessage(message: SignalingMessage) {
        val body = gson.toJson(message).toByteArray(StandardCharsets.UTF_8)
        require(body.size <= MAX_MESSAGE_BYTES) { "Signaling message exceeds $MAX_MESSAGE_BYTES bytes" }
        val connection = open(URL("$sessionUrl/messages"), "POST")
        try {
            connection.doOutput = true
            connection.setFixedLengthStreamingMode(body.size)
            connection.outputStream.use { it.write(body) }
            connection.readSuccessfulBody()
        } finally {
            connection.disconnect()
        }
    }

    private fun open(
        url: URL,
        method: String,
    ): HttpURLConnection =
        (url.openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = CONNECT_TIMEOUT_MS
            readTimeout = configuration.pollWaitSeconds * 1_000 + READ_TIMEOUT_MARGIN_MS
            setRequestProperty("Accept", "application/json")
            configuration.bearerTokenSecret.withString { token ->
                setRequestProperty("Authorization", "Bearer $token")
            }
            if (method == "POST") setRequestProperty("Content-Type", "application/json; charset=utf-8")
            useCaches = false
        }

    private fun HttpURLConnection.readSuccessfulBody(): String {
        val status = responseCode
        val stream = if (status in 200..299) inputStream else errorStream
        val body = stream?.bufferedReader(StandardCharsets.UTF_8)?.use { it.readTextLimited(MAX_RESPONSE_BYTES) }.orEmpty()
        if (status !in 200..299) {
            throw SignalingHttpException(status, body)
        }
        return body
    }

    private fun dispatch(event: SignalingEvent) {
        when (event.type) {
            TYPE_OFFER -> listener.onOffer(requireSdp(event.sdp))
            TYPE_ANSWER -> listener.onAnswer(requireSdp(event.sdp))
            TYPE_ICE_CANDIDATE -> {
                val candidate = event.candidate ?: throw IOException("ICE event omitted candidate")
                listener.onIceCandidate(
                    SignalingIceCandidate(
                        candidate = candidate.candidate ?: throw IOException("ICE event omitted candidate text"),
                        sdpMid = candidate.sdp_mid,
                        sdpMLineIndex = candidate.sdp_mline_index ?: throw IOException("ICE event omitted m-line index"),
                        usernameFragment = candidate.username_fragment,
                    ),
                )
            }
            TYPE_END_OF_CANDIDATES -> listener.onEndOfCandidates()
            else -> throw IOException("Unsupported signaling event type: ${event.type}")
        }
    }

    private fun reportFailure(failure: Throwable) {
        if (!closed.get()) listener.onFailure(failure)
    }

    private fun validateEventsResponse(
        response: EventsResponse,
        cursor: Long,
    ) {
        val nextCursor = response.next_cursor ?: throw IOException("Signaling response omitted next_cursor")
        val events = response.events ?: throw IOException("Signaling response omitted events")
        if (nextCursor < cursor) throw IOException("Signaling cursor moved backwards")
        var previousSequence = cursor
        events.forEach { event ->
            val sequence = event.sequence ?: throw IOException("Signaling event omitted sequence")
            if (sequence <= previousSequence || sequence > nextCursor) {
                throw IOException("Signaling events are not strictly ordered within next_cursor")
            }
            if (event.type.isNullOrBlank()) throw IOException("Signaling event omitted type")
            previousSequence = sequence
        }
    }

    private fun java.io.Reader.readTextLimited(limit: Int): String {
        val buffer = CharArray(4_096)
        val result = StringBuilder()
        while (true) {
            val count = read(buffer)
            if (count < 0) return result.toString()
            if (result.length + count > limit) throw IOException("Signaling response exceeds $limit characters")
            result.append(buffer, 0, count)
        }
    }

    private data class SignalingMessage(
        val message_id: String = "",
        val type: String,
        val sdp: String? = null,
        val candidate: CandidatePayload? = null,
    )

    private data class CandidatePayload(
        val candidate: String? = null,
        val sdp_mid: String? = null,
        val sdp_mline_index: Int? = null,
        val username_fragment: String? = null,
    )

    private data class SignalingEvent(
        val sequence: Long? = null,
        val type: String? = null,
        val sdp: String? = null,
        val candidate: CandidatePayload? = null,
    )

    private data class EventsResponse(
        val events: List<SignalingEvent>? = null,
        val next_cursor: Long? = null,
    )

    private class SignalingHttpException(
        val status: Int,
        body: String,
    ) : IOException("Signaling request failed with HTTP $status${body.takeIf { it.isNotBlank() }?.let { ": $it" }.orEmpty()}")

    private fun IOException.isRetryable(): Boolean =
        this !is SignalingHttpException || status == 408 || status == 429 || status >= 500

    companion object {
        private const val TYPE_OFFER = "offer"
        private const val TYPE_ANSWER = "answer"
        private const val TYPE_ICE_CANDIDATE = "ice_candidate"
        private const val TYPE_END_OF_CANDIDATES = "end_of_candidates"
        private const val CONNECT_TIMEOUT_MS = 10_000
        private const val READ_TIMEOUT_MARGIN_MS = 5_000
        private const val INITIAL_RETRY_DELAY_MS = 250
        private const val MAX_RETRY_DELAY_MS = 4_000
        private const val MAX_CONSECUTIVE_POLL_FAILURES = 6
        private const val MAX_POST_ATTEMPTS = 4
        private const val MAX_MESSAGE_BYTES = 1_048_576
        private const val MAX_RESPONSE_BYTES = 2_097_152

        private fun buildSessionUrl(
            baseUrl: String,
            sessionId: String,
        ): String {
            require(sessionId.matches(Regex("[A-Za-z0-9._-]{1,128}"))) { "Session ID contains unsafe characters" }
            return URI(baseUrl).toString().trimEnd('/') + "/v1/sessions/$sessionId"
        }

        private fun requireSdp(sdp: String?): String {
            require(!sdp.isNullOrBlank()) { "SDP must not be blank" }
            return sdp
        }

        private fun namedSingleThreadExecutor(name: String): ExecutorService =
            Executors.newSingleThreadExecutor { runnable ->
                Thread(runnable, name).apply { isDaemon = true }
            }
    }
}
