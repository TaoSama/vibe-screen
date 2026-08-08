package dev.telemachus.display.internet

/** Bounded frame queue: one active batch plus one newest replacement batch. */
internal class LatestFrameBatchQueue {
    private data class Batch(
        val records: List<ByteArray>,
        var nextRecordIndex: Int = 0,
    )

    private var active: Batch? = null
    private var pending: Batch? = null
    private var recordInFlight = false

    fun offer(frame: OutboundMediaFrame) {
        val replacement = Batch(frame.records.map(ByteArray::copyOf))
        val current = active
        when {
            current == null -> {
                active = replacement
                pending = null
            }
            current.nextRecordIndex == 0 && !recordInFlight -> {
                active = replacement
                pending = null
            }
            else -> pending = replacement
        }
    }

    fun nextRecord(): ByteArray? {
        if (recordInFlight) return null
        if (active == null) {
            active = pending
            pending = null
        }
        val batch = active ?: return null
        recordInFlight = true
        return batch.records[batch.nextRecordIndex]
    }

    fun completeRecord(accepted: Boolean): Boolean {
        if (!recordInFlight) return false
        recordInFlight = false
        if (!accepted) return true
        val batch = checkNotNull(active)
        batch.nextRecordIndex++
        if (batch.nextRecordIndex == batch.records.size) {
            active = pending
            pending = null
        }
        return true
    }

    fun sendNext(sendRecord: (ByteArray) -> Boolean): Boolean? {
        val record = nextRecord() ?: return null
        var committed = false
        try {
            val accepted = sendRecord(record)
            check(completeRecord(accepted)) { "Media record completion lost its in-flight batch" }
            committed = true
            return accepted
        } finally {
            if (!committed) {
                check(failRecord()) { "Media record failure lost its in-flight batch" }
            }
        }
    }

    private fun failRecord(): Boolean {
        if (!recordInFlight) return false
        clear()
        return true
    }

    fun hasWork(): Boolean = active != null || pending != null || recordInFlight

    fun clear() {
        active = null
        pending = null
        recordInFlight = false
    }
}
