package dev.telemachus.display

import android.content.Context
import android.content.RestrictionsManager
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import dev.telemachus.display.protocol.ProtocolV1Session
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ManagedConfigurationProviderInstrumentedTest {
    @Test
    fun realContextEmptyApplicationRestrictionsReturnUnmanagedPolicy() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val restrictionsManager =
            context.getSystemService(Context.RESTRICTIONS_SERVICE) as? RestrictionsManager

        assertNotNull("RestrictionsManager must be available on Android API 26+", restrictionsManager)
        val restrictions = checkNotNull(restrictionsManager).applicationRestrictions
        assertTrue(
            "This no-Host device-policy smoke test requires an unmanaged app-restrictions Bundle",
            restrictions.isEmpty,
        )

        assertEquals(
            ProtocolV1Session.ManagedPolicy.UNMANAGED,
            ManagedConfigurationProvider(context).loadPolicy(),
        )
    }
}
