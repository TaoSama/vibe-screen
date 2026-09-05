package dev.telemachus.display.audio

import android.util.Log
import androidx.test.ext.junit.runners.AndroidJUnit4
import dev.vibescreen.protocol.v1.AudioCodec
import dev.vibescreen.protocol.v1.AudioConfig
import dev.vibescreen.protocol.v1.AudioPacketHeader
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ProtocolPcmAudioPlayerInstrumentedTest {
    @Test
    fun androidAudioTrackOutputCanStartWriteAndCloseSyntheticPcm() {
        val player = ProtocolPcmAudioPlayer(AndroidAudioTrackOutputFactory())
        var stopped = false

        try {
            assertEquals(
                ProtocolAudioConfigureResult.Accepted(SMOKE_STREAM_ID, SMOKE_CONFIG_EPOCH),
                player.configure(
                    smokeAudioConfig(),
                    sessionEpoch = SMOKE_SESSION_EPOCH,
                ),
            )
            val format = requireNotNull(player.activeFormat())
            assertEquals(SMOKE_SAMPLE_RATE_HZ, format.sampleRateHz)
            assertEquals(SMOKE_CHANNEL_COUNT, format.channelCount)
            assertEquals(SMOKE_FRAMES_PER_PACKET, format.framesPerPacket)

            val payload = ByteArray(format.bytesPerPacket)
            val result =
                player.submit(
                    smokeAudioPacket(payload),
                )

            assertTrue("expected accepted Android AudioTrack write, got $result", result is ProtocolAudioPacketResult.Accepted)
            val accepted = result as ProtocolAudioPacketResult.Accepted
            assertEquals(AudioEnqueueResult.Queued, accepted.enqueueResult)
            assertEquals(1, accepted.writtenPackets)

            assertNull(player.stop())
            stopped = true
            assertNull(player.activeFormat())
            Log.i(TAG, "android_audio_track_smoke=start_write_close packets=1 bytes=${payload.size}")
        } finally {
            if (!stopped) {
                assertNull(player.stop())
            }
        }
    }

    private companion object {
        private const val TAG = "AudioTrackSmokeTest"
        private const val SMOKE_STREAM_ID = 41L
        private const val SMOKE_CONFIG_EPOCH = 2L
        private const val SMOKE_SESSION_EPOCH = 11L
        private const val SMOKE_SAMPLE_RATE_HZ = 48_000
        private const val SMOKE_CHANNEL_COUNT = 2
        private const val SMOKE_FRAMES_PER_PACKET = 480

        private fun smokeAudioConfig(): AudioConfig =
            AudioConfig
                .newBuilder()
                .setStreamId(SMOKE_STREAM_ID)
                .setConfigEpoch(SMOKE_CONFIG_EPOCH)
                .setCodec(AudioCodec.AUDIO_CODEC_PCM_S16LE)
                .setSampleRateHz(SMOKE_SAMPLE_RATE_HZ)
                .setChannelCount(SMOKE_CHANNEL_COUNT)
                .setFramesPerPacket(SMOKE_FRAMES_PER_PACKET)
                .build()

        private fun smokeAudioPacket(payload: ByteArray): ProtocolAudioPacket =
            ProtocolAudioPacket(
                AudioPacketHeader
                    .newBuilder()
                    .setStreamId(SMOKE_STREAM_ID)
                    .setSessionEpoch(SMOKE_SESSION_EPOCH)
                    .setConfigEpoch(SMOKE_CONFIG_EPOCH)
                    .setSequence(0)
                    .setFrameCount(SMOKE_FRAMES_PER_PACKET)
                    .setPayloadLength(payload.size)
                    .build(),
                payload,
            )
    }
}
