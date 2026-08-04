package dev.telemachus.display.internet

import com.google.gson.JsonArray
import com.google.gson.JsonObject
import com.google.gson.JsonParser

internal enum class RevocationCleanupStep(val failureLabel: String) {
    PAIRING_SECRET("pairing secret"),
    IDENTITY_KEY("identity key"),
    SESSION_CREDENTIALS("session credentials"),
    PAIRING_METADATA("pairing metadata"),
}

internal data class PendingRevocationCleanup(
    val pairingIdentifier: String,
    val localDeviceId: String,
    val identityEpoch: Long,
    val remainingSteps: Set<RevocationCleanupStep> = RevocationCleanupStep.entries.toSet(),
) {
    init {
        require(pairingIdentifier.isNotBlank() && localDeviceId.isNotBlank()) { "Revocation cleanup identities are required" }
        require(identityEpoch in 1 until Long.MAX_VALUE) {
            "Revocation cleanup identity epoch must be positive and below the reserved maximum"
        }
    }
}

internal data class RevocationCleanupResult(
    val remainingSteps: Set<RevocationCleanupStep>,
    val failures: Map<RevocationCleanupStep, Throwable>,
) {
    val complete: Boolean get() = remainingSteps.isEmpty()
}

/**
 * Executes all pending revocation work. A step is removed only after its
 * updated plan has been durably persisted, so a crash can only repeat an
 * idempotent deletion and can never forget unfinished work.
 */
internal fun retryRevocationCleanup(
    initial: PendingRevocationCleanup,
    execute: (RevocationCleanupStep) -> Unit,
    persist: (PendingRevocationCleanup?) -> Boolean,
): RevocationCleanupResult {
    var current = initial
    val failures = linkedMapOf<RevocationCleanupStep, Throwable>()
    RevocationCleanupStep.entries.forEach { step ->
        if (step !in current.remainingSteps) return@forEach
        try {
            execute(step)
            val remaining = current.remainingSteps - step
            val next = current.copy(remainingSteps = remaining)
            if (persist(next.takeUnless { it.remainingSteps.isEmpty() })) {
                current = next
            } else {
                failures[step] = IllegalStateException("Failed to persist revocation cleanup progress")
            }
        } catch (failure: Throwable) {
            failures[step] = failure
        }
    }
    return RevocationCleanupResult(current.remainingSteps, failures)
}

internal object PendingRevocationCleanupCodec {
    private val ROOT_KEYS = setOf("version", "pairing_id", "local_device_id", "identity_epoch", "remaining_steps")

    fun encode(pending: PendingRevocationCleanup): String =
        JsonObject().apply {
            addProperty("version", 1)
            addProperty("pairing_id", pending.pairingIdentifier)
            addProperty("local_device_id", pending.localDeviceId)
            addProperty("identity_epoch", pending.identityEpoch)
            add(
                "remaining_steps",
                JsonArray().apply {
                    RevocationCleanupStep.entries.filter { it in pending.remainingSteps }.forEach { add(it.name) }
                },
            )
        }.toString()

    fun decode(value: String): PendingRevocationCleanup {
        val root = JsonParser.parseString(value).asJsonObject
        require(root.keySet() == ROOT_KEYS && root.get("version")?.asInt == 1) { "Stored revocation cleanup is malformed" }
        val steps = root.getAsJsonArray("remaining_steps").map { RevocationCleanupStep.valueOf(it.asString) }.toSet()
        return PendingRevocationCleanup(
            pairingIdentifier = root.get("pairing_id").asString,
            localDeviceId = root.get("local_device_id").asString,
            identityEpoch = root.get("identity_epoch").asLong,
            remainingSteps = steps,
        )
    }
}
