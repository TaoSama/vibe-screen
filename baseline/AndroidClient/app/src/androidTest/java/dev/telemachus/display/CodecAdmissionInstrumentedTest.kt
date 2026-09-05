package dev.telemachus.display

import android.media.MediaFormat
import android.util.Log
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class CodecAdmissionInstrumentedTest {
    @Test
    fun av1DecoderProbeIsDiagnosticAndDoesNotOpenProductAdmission() {
        val av1Snapshot =
            AndroidDecoderCatalog.probe(
                mime = MediaFormat.MIMETYPE_VIDEO_AV1,
                width = DIAGNOSTIC_WIDTH,
                height = DIAGNOSTIC_HEIGHT,
                targetRate = DIAGNOSTIC_TARGET_RATE,
            )
        assertNotNull(
            "P0110 no-Host AV1 device-profile evidence requires a successful decoder catalog probe",
            av1Snapshot,
        )
        val av1Probes = checkNotNull(av1Snapshot).probes
        assertTrue(
            "P0110 no-Host AV1 device-profile evidence requires at least one real AV1 decoder probe",
            av1Probes.isNotEmpty(),
        )
        assertTrue(
            "P0110 no-Host AV1 device-profile evidence requires a hardware AV1 decoder candidate",
            av1Probes.any { !DecoderNameRules.isSoftware(it.name) },
        )
        val av1Selection = DecoderSelector.select(MediaFormat.MIMETYPE_VIDEO_AV1, checkNotNull(av1Snapshot))
        assertTrue(
            "P0110 no-Host AV1 device-profile evidence requires a selected diagnostic AV1 decoder",
            av1Selection is DecoderSelectionResult.Selected,
        )
        val runtimeSnapshot = CodecCapabilities.runtimeAdmissionSnapshot

        Log.i(
            TAG,
                "av1_probe=" +
                "probes=${av1Probes.map { it.name }} " +
                "failures=${av1Snapshot.capabilityProbeFailures} " +
                "selection=$av1Selection " +
                "usableAv1=${runtimeSnapshot.hasUsableAv1Decoder} " +
                "admission=${runtimeSnapshot.av1StreamAdmissionAvailable}",
        )

        assertFalse(
            "AV1 decoder discovery must stay separate from product stream admission",
            runtimeSnapshot.av1StreamAdmissionAvailable,
        )
        assertFalse(
            "AV1 must stay out of advertised USB/LAN product candidates",
            CodecFallbackPolicy.candidates(runtimeSnapshot).contains(StreamCodec.AV1),
        )
        assertFalse(
            "AV1 must stay closed even if a device exposes usable decode and a caller flips the staged frame flag",
            CodecRuntimeAdmissionSnapshot(
                hasUsableHevcDecoder = true,
                hasUsableAv1Decoder = true,
                av1FrameAdmissionEnabled = true,
            ).av1StreamAdmissionAvailable,
        )
        assertFalse(StreamCodecAdmissionSupport.hasFrameAdmissionImplementation(StreamCodec.AV1))
        assertNull(StreamCodec.AV1.toProtocolCodecOrNull())
        assertNull(StreamCodec.AV1.toProductVideoCodecOrNull())
    }

    private companion object {
        private const val TAG = "CodecAdmissionTest"
        private const val DIAGNOSTIC_WIDTH = 1280
        private const val DIAGNOSTIC_HEIGHT = 720
        private const val DIAGNOSTIC_TARGET_RATE = 60.0
    }
}
