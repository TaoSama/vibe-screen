package dev.telemachus.display

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class GestureShortcutPreferencesInstrumentedTest {
    @Test
    fun gestureShortcutChoicesRoundTripThroughSharedPreferences() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val preferencesName = "gesture-shortcuts-" + UUID.randomUUID()
        val preferences = PreferencesManager(context, preferencesName)

        assertEquals(GestureHostActionChoice.DEFAULT, preferences.gestureSwipeUpAction)
        assertEquals(GestureHostActionChoice.DEFAULT, preferences.gestureSwipeDownAction)

        preferences.gestureSwipeUpAction = GestureHostActionChoice.MOVE_WINDOW
        preferences.gestureSwipeDownAction = GestureHostActionChoice.RETURN_WINDOWS

        assertEquals(GestureHostActionChoice.MOVE_WINDOW, preferences.gestureSwipeUpAction)
        assertEquals(GestureHostActionChoice.RETURN_WINDOWS, preferences.gestureSwipeDownAction)

        context
            .getSharedPreferences(preferencesName, Context.MODE_PRIVATE)
            .edit()
            .putString("gesture_swipe_up_action", "unknown-action")
            .apply()
        assertEquals(GestureHostActionChoice.DEFAULT, preferences.gestureSwipeUpAction)
    }
}
