package dev.telemachus.display

import android.annotation.SuppressLint
import android.content.Context
import android.content.SharedPreferences
import java.util.UUID

class PreferencesManager(
    context: Context,
    preferencesName: String = "app_prefs",
) {
    private val prefs: SharedPreferences = context.getSharedPreferences(preferencesName, Context.MODE_PRIVATE)

    var showStatsOverlay: Boolean
        get() = prefs.getBoolean("show_stats", false)
        set(value) = prefs.edit().putBoolean("show_stats", value).apply()

    var overlayOpacity: Float
        get() = prefs.getFloat("overlay_opacity", 0.8f)
        set(value) = prefs.edit().putFloat("overlay_opacity", value).apply()

    var overlayX: Float
        get() = prefs.getFloat("overlay_x", -1f)
        set(value) = prefs.edit().putFloat("overlay_x", value).apply()

    var overlayY: Float
        get() = prefs.getFloat("overlay_y", -1f)
        set(value) = prefs.edit().putFloat("overlay_y", value).apply()

    var connectionMode: ConnectionMode
        get() = ConnectionMode.fromName(prefs.getString("connection_mode", null))
        set(value) = prefs.edit().putString("connection_mode", value.name).apply()

    var trustedLanAcknowledged: Boolean
        get() = prefs.getBoolean("trusted_lan_acknowledged", false)
        set(value) = prefs.edit().putBoolean("trusted_lan_acknowledged", value).apply()

    var videoScaleMode: VideoScaleMode
        get() = VideoScaleMode.fromName(prefs.getString("video_scale_mode", null))
        set(value) = prefs.edit().putString("video_scale_mode", value.name).apply()

    var clientRotation: ClientRotation
        get() = ClientRotation.fromName(prefs.getString("client_rotation", null))
        set(value) = prefs.edit().putString("client_rotation", value.name).apply()

    var videoQuality: VideoQualityChoice
        get() = VideoQualityChoice.fromName(prefs.getString("video_quality", null))
        set(value) = prefs.edit().putString("video_quality", value.name).apply()

    var videoBitrateMbps: Int
        get() = prefs.getInt("video_bitrate_mbps", ClientVideoBounds.DEFAULT_BITRATE_MBPS)
        set(value) = prefs.edit().putInt("video_bitrate_mbps", value).apply()

    var videoFrameRate: Int
        get() = prefs.getInt("video_frame_rate", ClientVideoBounds.DEFAULT_FRAME_RATE)
        set(value) = prefs.edit().putInt("video_frame_rate", value).apply()

    var gestureSwipeUpAction: GestureHostActionChoice
        get() = GestureHostActionChoice.fromName(prefs.getString("gesture_swipe_up_action", null))
        set(value) = prefs.edit().putString("gesture_swipe_up_action", value.name).apply()

    var gestureSwipeDownAction: GestureHostActionChoice
        get() = GestureHostActionChoice.fromName(prefs.getString("gesture_swipe_down_action", null))
        set(value) = prefs.edit().putString("gesture_swipe_down_action", value.name).apply()

    var internetForceRelay: Boolean
        get() = prefs.getBoolean("internet_force_relay", false)
        set(value) = prefs.edit().putBoolean("internet_force_relay", value).apply()

    @get:SuppressLint("ApplySharedPref") // Identity creation must be durable before a Keystore key is bound to it.
    val internetDeviceId: String
        get() {
            prefs.getString("internet_device_id", null)?.takeIf(String::isNotBlank)?.let { return it }
            val created = "android-${UUID.randomUUID()}"
            check(prefs.edit().putString("internet_device_id", created).commit()) {
                "Failed to persist the Internet device identity"
            }
            return created
        }
}
