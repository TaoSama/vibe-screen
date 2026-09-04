package dev.telemachus.display

internal enum class HeartbeatTelemetrySource(val wireValue: String) {
    LEGACY("legacy"),
    CONTROL("control"),
    AUDIO("audio"),
    BULK("bulk"),
}

internal data class HeartbeatTelemetryEvent(
    val sessionEpoch: Long,
    val wireMode: String,
    val source: HeartbeatTelemetrySource,
) {
    fun fields(): Map<String, Any?> =
        mapOf(
            "session_epoch" to sessionEpoch,
            "wire_mode" to wireMode,
            "source" to source.wireValue,
        )
}

internal class HeartbeatTelemetryReporter(
    private val intervalNs: Long,
) {
    private val lock = Any()
    private var lastEmitNs = 0L

    fun reset() {
        synchronized(lock) {
            lastEmitNs = 0L
        }
    }

    fun record(
        nowNs: Long,
        sessionEpoch: Long,
        wireMode: String,
        source: HeartbeatTelemetrySource,
        emit: (HeartbeatTelemetryEvent) -> Unit,
    ): Boolean =
        synchronized(lock) {
            if (lastEmitNs != 0L && nowNs - lastEmitNs < intervalNs) return@synchronized false
            lastEmitNs = nowNs
            emit(HeartbeatTelemetryEvent(sessionEpoch, wireMode, source))
            true
        }
}
