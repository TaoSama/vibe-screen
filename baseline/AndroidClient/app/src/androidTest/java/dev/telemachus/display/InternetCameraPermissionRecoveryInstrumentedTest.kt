package dev.telemachus.display

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.ParcelFileDescriptor
import android.os.SystemClock
import android.provider.Settings
import androidx.core.content.ContextCompat
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.espresso.Espresso
import androidx.test.espresso.Espresso.onView
import androidx.test.espresso.NoMatchingViewException
import androidx.test.espresso.assertion.ViewAssertions.matches
import androidx.test.espresso.matcher.ViewMatchers.isDisplayed
import androidx.test.espresso.matcher.ViewMatchers.withId
import androidx.test.espresso.matcher.ViewMatchers.withText
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class InternetCameraPermissionRecoveryInstrumentedTest {
    @Test
    fun visibleInternetPermissionPanelGrantedOutsideAppLaunchesScannerOnForegroundReturn() {
        assumeTrue(
            "Pass -e $OPT_IN_ARGUMENT true after denying Camera from adb for this focused recovery run",
            InstrumentationRegistry.getArguments().getString(OPT_IN_ARGUMENT, "false").toBoolean(),
        )
        val context = ApplicationProvider.getApplicationContext<Context>()
        val preferences = PreferencesManager(context)
        val originalMode = preferences.connectionMode
        try {
            assertTrue(
                "Focused recovery run must start with Camera denied by the host-side adb setup",
                !context.isCameraGranted(),
            )
            preferences.connectionMode = ConnectionMode.INTERNET

            ActivityScenario.launch(MainActivity::class.java).use { scenario ->
                onView(withId(R.id.internetModeContent)).check(matches(isDisplayed()))
                scenario.onActivity { activity ->
                    activity.setPrivateField(
                        "internetCameraPermissionPanelState",
                        InternetCameraPermissionPanelState.FIRST_DENIED,
                    )
                    activity.invokePrivateNoArgs("renderInternetCameraPermissionPanel")
                }
                onView(withId(R.id.internetCameraPermissionPanel)).check(matches(isDisplayed()))
                onView(withId(R.id.internetCameraPermissionMessage))
                    .check(matches(withText(R.string.internet_camera_permission_retry_instructions)))

                context.openSystemAppInfoFromShell()
                waitForFocusedPackage(SYSTEM_SETTINGS_PACKAGE)
                context.grantCameraPermissionFromShell()
                context.waitForCameraPermission(granted = true)
                pressBackWithShell()
                waitForFocusedPackage(context.packageName)

                waitForDisplayed(R.id.preview) {
                    scenario.cameraRecoverySnapshot(context)
                }
                Espresso.pressBack()
                onView(withId(R.id.internetModeContent)).check(matches(isDisplayed()))
            }
        } finally {
            preferences.connectionMode = originalMode
        }
    }

    private fun Context.isCameraGranted(): Boolean =
        ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED

    private fun Context.grantCameraPermissionFromShell() {
        val automation = InstrumentationRegistry.getInstrumentation().uiAutomation
        automation.executeShellCommand("pm grant $packageName ${Manifest.permission.CAMERA}").close()
    }

    private fun Context.openSystemAppInfoFromShell() {
        InstrumentationRegistry.getInstrumentation().uiAutomation
            .executeShellCommand(
                "am start -a ${Settings.ACTION_APPLICATION_DETAILS_SETTINGS} -d package:$packageName",
            )
            .close()
    }

    private fun pressBackWithShell() {
        InstrumentationRegistry.getInstrumentation().uiAutomation
            .executeShellCommand("input keyevent KEYCODE_BACK")
            .close()
    }

    private fun Context.waitForCameraPermission(granted: Boolean) {
        val deadline = SystemClock.uptimeMillis() + PERMISSION_WAIT_TIMEOUT_MS
        while (SystemClock.uptimeMillis() < deadline) {
            if (isCameraGranted() == granted) return
            SystemClock.sleep(PERMISSION_POLL_INTERVAL_MS)
        }
        assertTrue(
            "Camera permission did not become $granted",
            isCameraGranted() == granted,
        )
    }

    private fun Any.setPrivateField(
        name: String,
        value: Any?,
    ) {
        privateField(name).set(this, value)
    }

    private fun Any.getPrivateField(name: String): Any? = privateField(name).get(this)

    private fun Any.invokePrivateNoArgs(name: String) {
        MainActivity::class.java.getDeclaredMethod(name).apply { isAccessible = true }.invoke(this)
    }

    private fun Any.privateField(name: String) =
        MainActivity::class.java.getDeclaredField(name).apply { isAccessible = true }

    private fun ActivityScenario<MainActivity>.cameraRecoverySnapshot(context: Context): String {
        var snapshot = "<activity unavailable>"
        onActivity { activity ->
            snapshot =
                "panelState=${activity.getPrivateField("internetCameraPermissionPanelState")}, " +
                    "settingsPending=${activity.getPrivateField("internetCameraSettingsReturnPending")}, " +
                    "mode=${PreferencesManager(context).connectionMode}, " +
                    "cameraGranted=${context.isCameraGranted()}, " +
                    "focus=${currentWindowFocus()}"
        }
        return snapshot
    }

    private fun waitForDisplayed(
        viewId: Int,
        diagnostics: () -> String = { "" },
    ) {
        val deadline = SystemClock.uptimeMillis() + VIEW_WAIT_TIMEOUT_MS
        var lastFailure: Throwable? = null
        while (SystemClock.uptimeMillis() < deadline) {
            try {
                onView(withId(viewId)).check(matches(isDisplayed()))
                return
            } catch (failure: NoMatchingViewException) {
                lastFailure = failure
            } catch (failure: AssertionError) {
                lastFailure = failure
            }
            SystemClock.sleep(VIEW_POLL_INTERVAL_MS)
        }
        throw AssertionError("View $viewId was not displayed. ${diagnostics()}", lastFailure)
    }

    private fun waitForFocusedPackage(packageName: String) {
        val deadline = SystemClock.uptimeMillis() + FOCUS_WAIT_TIMEOUT_MS
        var lastFocus = ""
        while (SystemClock.uptimeMillis() < deadline) {
            lastFocus = currentWindowFocus()
            if (lastFocus.lineSequence().any { line -> line.contains("mCurrentFocus") && line.contains("$packageName/") }) {
                return
            }
            SystemClock.sleep(VIEW_POLL_INTERVAL_MS)
        }
        throw AssertionError("Focused window did not contain exact package $packageName. Last focus: $lastFocus")
    }

    private fun currentWindowFocus(): String =
        InstrumentationRegistry.getInstrumentation().uiAutomation
            .executeShellCommand("dumpsys window")
            .let { descriptor ->
                ParcelFileDescriptor.AutoCloseInputStream(descriptor).use { stream ->
                    stream.readBytes().decodeToString()
                }
            }
            .lineSequence()
            .filter { line -> line.contains("mCurrentFocus") }
            .joinToString("\n")

    private companion object {
        private const val OPT_IN_ARGUMENT = "vibeScreenInternetCameraRecovery"
        private const val SYSTEM_SETTINGS_PACKAGE = "com.android.settings"
        private const val PERMISSION_WAIT_TIMEOUT_MS = 3_000L
        private const val FOCUS_WAIT_TIMEOUT_MS = 5_000L
        private const val PERMISSION_POLL_INTERVAL_MS = 100L
        private const val VIEW_WAIT_TIMEOUT_MS = 5_000L
        private const val VIEW_POLL_INTERVAL_MS = 100L
    }
}
