package dev.telemachus.display

internal object ControllerDispatchOrdering {
    fun disconnectsBeforeLaterEpochSamples(dispatch: ControllerDispatch): ControllerDispatch {
        val ordered = disconnectsBeforeLaterEpochSamples(dispatch.samples)
        return if (ordered === dispatch.samples) dispatch else dispatch.copy(samples = ordered)
    }

    fun hasLaterLowerEpochDisconnect(samples: List<ControllerStateSample>): Boolean =
        samples.indices.any { index ->
            hasLaterLowerEpochDisconnect(samples, index, samples[index])
        }

    fun hasLaterLowerEpochDisconnect(
        samples: List<ControllerStateSample>,
        index: Int,
        sample: ControllerStateSample,
    ): Boolean = samples.asSequence().drop(index + 1).any { later ->
        later.kind == ControllerEventKind.DISCONNECTED &&
            later.controllerId == sample.controllerId &&
            later.controllerEpoch < sample.controllerEpoch
    }

    fun hasLaterSameConnectionConnected(
        samples: List<ControllerStateSample>,
        index: Int,
        sample: ControllerStateSample,
    ): Boolean {
        if (sample.kind == ControllerEventKind.CONNECTED) return false
        return samples.asSequence().drop(index + 1).any { later ->
            later.kind == ControllerEventKind.CONNECTED &&
                later.controllerId == sample.controllerId &&
                later.controllerEpoch == sample.controllerEpoch
        }
    }

    fun disconnectsBeforeLaterEpochSamples(samples: List<ControllerStateSample>): List<ControllerStateSample> {
        if (samples.size < 2) return samples
        val remaining = samples.toMutableList()
        val ordered = ArrayList<ControllerStateSample>(samples.size)
        var changed = false
        while (remaining.isNotEmpty()) {
            val nextIndex =
                remaining.indices.firstOrNull { index ->
                    val sample = remaining[index]
                    !hasLaterLowerEpochDisconnect(remaining, index, sample) &&
                        !hasLaterSameConnectionConnected(remaining, index, sample)
                } ?: 0
            if (nextIndex != 0) changed = true
            ordered += remaining.removeAt(nextIndex)
        }
        return if (changed) ordered else samples
    }
}
