package dev.telemachus.display

import android.media.MediaFormat
import org.junit.Assert.assertEquals
import org.junit.Test

class VideoDecoderSdrColorSettingsTest {
    @Test
    fun sdrColorSettingsPinBt709EightBitSurfaceDecode() {
        val properties = VideoDecoderSdrColorSettings.integerProperties.toMap()

        assertEquals(MediaFormat.COLOR_STANDARD_BT709, properties[MediaFormat.KEY_COLOR_STANDARD])
        assertEquals(MediaFormat.COLOR_TRANSFER_SDR_VIDEO, properties[MediaFormat.KEY_COLOR_TRANSFER])
        assertEquals(MediaFormat.COLOR_RANGE_LIMITED, properties[MediaFormat.KEY_COLOR_RANGE])
    }
}
