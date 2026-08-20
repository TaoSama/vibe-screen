package dev.telemachus.display.internet.security

import dev.telemachus.display.internet.InternetAudioRecordContract
import dev.telemachus.display.internet.InternetBulkRecordContract

data class AdvancedChannelOwner(
    val sessionId: String,
    val sessionEpoch: Long,
    val generation: Long,
) {
    val isValid: Boolean
        get() = sessionId.isNotBlank() && sessionEpoch > 0 && generation > 0
}

sealed interface AdvancedChannelBinding {
    val channel: SecurityChannel
    val isValid: Boolean

    data class Audio(
        val displayId: String,
        val streamId: Long,
    ) : AdvancedChannelBinding {
        override val channel = SecurityChannel.AUDIO
        override val isValid: Boolean
            get() = displayId.isNotBlank() && displayId.toByteArray(Charsets.UTF_8).size <= 128 && streamId > 0
    }

    class Bulk(transferId: ByteArray) : AdvancedChannelBinding {
        private val value = transferId.copyOf()
        val transferId: ByteArray
            get() = value.copyOf()
        override val channel = SecurityChannel.BULK
        override val isValid: Boolean
            get() = value.size in 16..64

        override fun equals(other: Any?): Boolean =
            other is Bulk && value.contentEquals(other.value)

        override fun hashCode(): Int = value.contentHashCode()
    }
}

data class AdvancedChannelAdmission(
    val id: Long,
    val owner: AdvancedChannelOwner,
    val binding: AdvancedChannelBinding,
    val plaintextBytes: Int,
)

class AdvancedChannelSecurityGate(
    initialOwner: AdvancedChannelOwner,
    private val limits: Limits = Limits.STANDARD,
) {
    data class Limits(
        val maximumAudioRecordBytes: Int,
        val maximumAudioBacklogBytes: Int,
        val maximumBulkRecordBytes: Int,
        val maximumBulkBacklogBytes: Int,
    ) {
        companion object {
            val STANDARD =
                Limits(
                    maximumAudioRecordBytes = InternetAudioRecordContract.MAXIMUM_PLAINTEXT_RECORD_BYTES,
                    maximumAudioBacklogBytes = 1024 * 1024,
                    maximumBulkRecordBytes = InternetBulkRecordContract.MAXIMUM_PLAINTEXT_RECORD_BYTES,
                    maximumBulkBacklogBytes = 4 * 1024 * 1024,
                )
        }
    }

    private var owner = initialOwner.also { require(it.isValid) { "Advanced channel owner is invalid" } }
    private var nextId = 1L
    private val admissions = mutableMapOf<Long, AdvancedChannelAdmission>()
    private val bufferedBytes = mutableMapOf<SecurityChannel, Int>()

    init {
        require(limits.maximumAudioRecordBytes > 0) { "Audio record limit must be positive" }
        require(limits.maximumAudioBacklogBytes >= limits.maximumAudioRecordBytes) {
            "Audio backlog limit must cover one record"
        }
        require(limits.maximumBulkRecordBytes > 0) { "Bulk record limit must be positive" }
        require(limits.maximumBulkBacklogBytes >= limits.maximumBulkRecordBytes) {
            "Bulk backlog limit must cover one record"
        }
    }

    @Synchronized
    fun reserve(
        payloadBytes: Int,
        binding: AdvancedChannelBinding,
        candidateOwner: AdvancedChannelOwner,
    ): AdvancedChannelAdmission {
        check(candidateOwner == owner) { "Advanced channel owner is stale" }
        require(binding.isValid) { "Advanced channel binding is invalid" }
        require(payloadBytes > 0) { "Advanced channel payload is empty" }
        val maximumRecord =
            if (binding.channel == SecurityChannel.AUDIO) limits.maximumAudioRecordBytes else limits.maximumBulkRecordBytes
        val maximumBacklog =
            if (binding.channel == SecurityChannel.AUDIO) limits.maximumAudioBacklogBytes else limits.maximumBulkBacklogBytes
        require(payloadBytes <= maximumRecord) { "Advanced channel payload exceeds $maximumRecord bytes" }
        val buffered = bufferedBytes[binding.channel] ?: 0
        check(buffered <= maximumBacklog - payloadBytes) { "Advanced channel backlog exceeds $maximumBacklog bytes" }
        check(nextId < Long.MAX_VALUE) { "Advanced channel admission sequence is exhausted" }
        val admission = AdvancedChannelAdmission(nextId++, candidateOwner, binding, payloadBytes)
        admissions[admission.id] = admission
        bufferedBytes[binding.channel] = buffered + payloadBytes
        return admission
    }

    @Synchronized
    fun finish(admission: AdvancedChannelAdmission) {
        check(admission.owner == owner) { "Advanced channel owner is stale" }
        check(admissions[admission.id] == admission) { "Advanced channel admission is unknown" }
        admissions.remove(admission.id)
        val channel = admission.binding.channel
        bufferedBytes[channel] = maxOf(0, (bufferedBytes[channel] ?: 0) - admission.plaintextBytes)
    }

    @Synchronized
    fun replaceOwner(replacement: AdvancedChannelOwner) {
        require(replacement.isValid) { "Advanced channel owner is invalid" }
        owner = replacement
        nextId = 1
        admissions.clear()
        bufferedBytes.clear()
    }

    @Synchronized
    fun bufferedBytes(channel: SecurityChannel): Int = bufferedBytes[channel] ?: 0
}
