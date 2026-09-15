package dev.telemachus.display

import android.content.Context
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.espresso.Espresso
import androidx.test.espresso.Espresso.onView
import androidx.test.espresso.action.ViewActions.click
import androidx.test.espresso.assertion.ViewAssertions.matches
import androidx.test.espresso.matcher.ViewMatchers.isDisplayed
import androidx.test.espresso.matcher.ViewMatchers.withId
import androidx.test.espresso.matcher.ViewMatchers.withText
import androidx.test.ext.junit.runners.AndroidJUnit4
import dev.telemachus.display.audio.PcmAudioStreamFormat
import org.hamcrest.Matchers.not
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class InternetAudioReadinessSettingsInstrumentedTest {
    @After
    fun clearInternetAudioOverride() {
        MainActivityInternetAudioReadinessTestHooks.setOverride(null)
    }

    @Test
    fun internetSettingsAudioReadinessUsesInternetSnapshotAndClearsAfterDisconnect() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val preferences = PreferencesManager(context)
        val originalMode = preferences.connectionMode
        val format =
            PcmAudioStreamFormat(
                streamId = 11,
                configEpoch = 3,
                sampleRateHz = 48_000,
                channelCount = 2,
                framesPerPacket = 480,
            )
        try {
            preferences.connectionMode = ConnectionMode.INTERNET
            MainActivityInternetAudioReadinessTestHooks.setOverride(
                MainActivityInternetAudioReadinessTestHooks.Override(
                    active = true,
                    snapshot = AudioReadinessSnapshot(format, acceptedPacketCount = 3, writtenPacketCount = 2),
                ),
            )

            ActivityScenario.launch(MainActivity::class.java).use {
                onView(withId(R.id.modeInternet)).perform(click())
                onView(withId(R.id.internetConnectionSettingsButton)).perform(click())

                onView(withId(R.id.audioReadinessStatus))
                    .check(matches(withText(R.string.audio_readiness_ready_status)))
                onView(withId(R.id.audioReadinessSummary))
                    .check(
                        matches(
                            withText(
                                context.getString(
                                    R.string.audio_readiness_ready_summary,
                                    format.sampleRateHz,
                                    format.channelCount,
                                    format.framesPerPacket,
                                ),
                            ),
                        ),
                    )
                onView(withId(R.id.audioReadinessCounters))
                    .check(matches(isDisplayed()))
                    .check(matches(withText(context.getString(R.string.audio_readiness_counters, 3, 2))))

                Espresso.pressBack()
                MainActivityInternetAudioReadinessTestHooks.setOverride(
                    MainActivityInternetAudioReadinessTestHooks.Override(active = false, snapshot = null),
                )
                onView(withId(R.id.internetConnectionSettingsButton)).perform(click())

                onView(withId(R.id.audioReadinessStatus))
                    .check(matches(withText(R.string.audio_readiness_waiting_status)))
                onView(withId(R.id.audioReadinessSummary))
                    .check(matches(withText(R.string.audio_readiness_waiting_summary)))
                onView(withId(R.id.audioReadinessCounters)).check(matches(not(isDisplayed())))
            }
        } finally {
            preferences.connectionMode = originalMode
            MainActivityInternetAudioReadinessTestHooks.setOverride(null)
        }
    }
}
