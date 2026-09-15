package dev.telemachus.display

import android.Manifest
import android.content.Context
import android.os.SystemClock
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.EditText
import android.widget.TextView
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.espresso.Espresso.onView
import androidx.test.espresso.AppNotIdleException
import androidx.test.espresso.IdlingResourceTimeoutException
import androidx.test.espresso.NoMatchingRootException
import androidx.test.espresso.NoMatchingViewException
import androidx.test.espresso.Root
import androidx.test.espresso.UiController
import androidx.test.espresso.ViewAction
import androidx.test.espresso.action.ViewActions.click
import androidx.test.espresso.assertion.ViewAssertions.matches
import androidx.test.espresso.matcher.ViewMatchers.isChecked
import androidx.test.espresso.matcher.ViewMatchers.isDisplayed
import androidx.test.espresso.matcher.ViewMatchers.isEnabled
import androidx.test.espresso.matcher.ViewMatchers.withHint
import androidx.test.espresso.matcher.ViewMatchers.withId
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.rule.GrantPermissionRule
import dev.telemachus.display.internet.InternetProductRevocationCoordinator
import dev.telemachus.display.internet.InternetSessionProfileStore
import dev.telemachus.display.internet.security.AndroidDeviceIdentityStore
import dev.telemachus.display.internet.security.AndroidSecretStore
import dev.telemachus.display.internet.security.AndroidStoredInternetSessionFactory
import dev.telemachus.display.internet.security.InternetPairingAcceptance
import dev.telemachus.display.internet.security.InternetPairingRequest
import java.security.MessageDigest
import java.util.concurrent.atomic.AtomicReference
import org.hamcrest.Description
import org.hamcrest.Matchers.allOf
import org.hamcrest.Matchers.not
import org.hamcrest.TypeSafeMatcher
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Real device-side acceptance harness for Internet pairing with CameraX + ZXing decode.
 *
 * This test drives the real Android rear camera via CameraX ImageAnalysis and ZXing
 * QRCodeReader decode. It strictly forbids addMonitor, ActivityResult injection, direct
 * onActivityResult calls, reflection on beginInternetPairing, or direct invocation of
 * analyze/deliverResult.
 *
 * The raw offer URL is written to an app-private file (0600) so the Mac host runner
 * can present it as a QR code using an AppKit/CoreImage window.
 */
@RunWith(AndroidJUnit4::class)
class RealQrInternetPairingInstrumentedTest {
    @Volatile
    private var acceptanceStage = "initialization"

    @get:Rule
    val cameraPermission: GrantPermissionRule = GrantPermissionRule.grant(Manifest.permission.CAMERA)

    @Test
    fun realCameraQrPairingAndRevokeAreAcceptedThroughMainActivity() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val profileStore = InternetSessionProfileStore(context)
        val preferences = PreferencesManager(context)
        val deviceId = preferences.internetDeviceId
        val storedFactory = AndroidStoredInternetSessionFactory(context, deviceId)
        val revocationCoordinator = InternetProductRevocationCoordinator.processShared()

        assertTrue("Acceptance requires a clean profile store", profileStore.loadPublicProfile() == null)
        assertFalse("Acceptance requires a clean pairing store", profileStore.hasVerifiedPairing())
        revocationCoordinator.withCredentialMutationAdmission(durableBlock = { false }) {
            assertFalse("Acceptance requires a clean pairing transaction", storedFactory.hasPendingPairingPersistenceCleanup())
        }

        preferences.apply {
            connectionMode = ConnectionMode.USB
            internetForceRelay = false
        }
        val initialIdentityHighWatermark = identityHighWatermark(context)
        val createdOffers = mutableListOf<TestPairingOffer>()
        val createdLeases = mutableListOf<Pair<TestPairingOffer, TestLease>>()
        val authority = TestHostAuthority()
        val firstEpoch = System.currentTimeMillis().coerceAtLeast(1L)

        val offerFileName = InternetPairingTestHooks.FILE_INTERNET_PAIRING_OFFER
        val markerFileName = InternetPairingTestHooks.FILE_QR_SCAN_MARKER
        val requestFileName = InternetPairingTestHooks.FILE_QR_SCAN_MARKER_REQUEST

        InternetPairingTestHooks.deleteAppPrivateFile(context, offerFileName)
        InternetPairingTestHooks.deleteAppPrivateFile(context, markerFileName)
        InternetPairingTestHooks.deleteAppPrivateFile(context, requestFileName)

        var primaryFailure: Throwable? = null
        try {
            ActivityScenario.launch(MainActivity::class.java).use { scenario ->
                acceptanceStage = "internet_tab"
                onView(withId(R.id.modeInternet)).perform(click())
                onView(withId(R.id.internetModeContent)).check(matches(isDisplayed()))

                val firstOffer = authority.createOffer().also(createdOffers::add)
                InternetPairingTestHooks.writeAppPrivateText(context, offerFileName, firstOffer.encodedUrl)
                waitForPresenterReady(
                    context = context,
                    requestFileName = requestFileName,
                    expectedOfferSha256 = InternetPairingTestHooks.sha256Hex(firstOffer.encodedUrl),
                )

                acceptanceStage = "real_camera_qr_scan_trigger"
                scenario.onActivity { activity ->
                    check(activity.findViewById<View>(R.id.internetScanProfileButton).performClick()) {
                        "Internet pairing scan action was not handled"
                    }
                }

                acceptanceStage = "await_camera_zxing_decode_and_dialog"
                val rawRequest = waitForPairingRequestDialog(timeoutMs = 60_000)
                val firstRequest = InternetPairingRequest.parse(rawRequest)

                acceptanceStage = "verify_real_camerax_zxing_marker"
                val markerRaw = InternetPairingTestHooks.readAppPrivateText(context, markerFileName)
                assertNotNull("QR scan marker must be written by CameraX/ZXing", markerRaw)
                val marker = JSONObject(checkNotNull(markerRaw))
                assertEquals(InternetPairingTestHooks.QR_SCAN_MARKER_SCHEMA, marker.getString("schema"))
                assertEquals("CameraX ImageAnalysis", marker.getString("source"))
                assertEquals("ZXing QRCodeReader", marker.getString("decoder"))
                assertEquals(InternetPairingTestHooks.sha256Hex(firstOffer.encodedUrl), marker.getString("payload_sha256"))
                assertTrue("Camera frame width must be > 0", marker.getInt("frame_width") > 0)
                assertTrue("Camera frame height must be > 0", marker.getInt("frame_height") > 0)
                assertTrue("Luma width must be > 0", marker.getInt("luma_width") > 0)
                assertTrue("Luma height must be > 0", marker.getInt("luma_height") > 0)

                acceptanceStage = "first_pairing_acceptance"
                completePairing(authority.accept(firstOffer, firstRequest))
                assertTrue(profileStore.hasVerifiedPairing())
                onView(withId(R.id.internetConnectButton)).check(matches(not(isEnabled())))

                val firstLease = authority.issueLease(firstOffer, firstRequest, firstEpoch)
                createdLeases += firstOffer to firstLease
                acceptanceStage = "first_lease_import"
                importLease(scenario, firstLease.encoded)
                assertEquals(firstEpoch, profileStore.loadPublicProfile()?.authoritativeSessionEpoch)
                onView(withId(R.id.internetConnectButton)).check(matches(isEnabled()))

                acceptanceStage = "first_revoke"
                revokeThroughUi(scenario)
                assertTrue("Local revoke retained a profile", profileStore.loadPublicProfile() == null)
                assertFalse(profileStore.hasVerifiedPairing())
                assertSecretsRemoved(context, firstOffer, firstLease)
            }
        } catch (failure: Throwable) {
            primaryFailure = failure
            throw failure
        } finally {
            InternetPairingTestHooks.deleteAppPrivateFile(context, requestFileName)
            InternetPairingTestHooks.deleteAppPrivateFile(context, offerFileName)
            val cleanupFailure =
                cleanupCreatedCredentials(
                    context = context,
                    deviceId = deviceId,
                    initialIdentityHighWatermark = initialIdentityHighWatermark,
                    profileStore = profileStore,
                    storedFactory = storedFactory,
                    revocationCoordinator = revocationCoordinator,
                    createdOffers = createdOffers,
                    createdLeases = createdLeases,
                )
            if (cleanupFailure != null) {
                val redacted = AssertionError("Acceptance credential cleanup was incomplete")
                if (primaryFailure == null) throw redacted else primaryFailure.addSuppressed(redacted)
            }
        }

        println(
            "PHASE3_REAL_QR_PAIRING_PASS real_camerax_zxing=true in_memory_authority=true " +
                "pairing=true strict_lease_import=true local_revoke=true secure_dialogs=true",
        )
    }

    private fun waitForPairingRequestDialog(timeoutMs: Long = 60_000): String {
        val started = SystemClock.uptimeMillis()
        val requestRef = AtomicReference<String>()
        while (SystemClock.uptimeMillis() - started < timeoutMs) {
            try {
                onView(withId(R.id.internetPairingRequestText))
                    .inRoot(RealQrDialogTextRootMatcher(R.string.internet_pairing_complete_title))
                    .perform(RealQrCapturePairingRequestAction(requestRef))
                val captured = requestRef.get()
                if (captured != null) return captured
            } catch (_: NoMatchingViewException) {
                // Dialog view not found yet; keep waiting for CameraX to scan the presented QR code.
            } catch (_: NoMatchingRootException) {
                // Dialog window root not created yet; keep waiting.
            } catch (_: AppNotIdleException) {
                // Main thread busy / transitioning; keep waiting.
            } catch (_: IdlingResourceTimeoutException) {
                // Idling resource timed out; keep waiting.
            }
            SystemClock.sleep(250)
        }
        throw AssertionError("Pairing request dialog did not appear within ${timeoutMs}ms; CameraX/ZXing scan timed out")
    }

    private fun waitForPresenterReady(
        context: Context,
        requestFileName: String,
        expectedOfferSha256: String,
        timeoutMs: Long = 30_000,
    ) {
        acceptanceStage = "await_presenter_ready"
        val started = SystemClock.uptimeMillis()
        while (SystemClock.uptimeMillis() - started < timeoutMs) {
            val raw = InternetPairingTestHooks.readAppPrivateText(context, requestFileName)
            if (raw != null) {
                val request = JSONObject(raw)
                check(request.getString("schema") == InternetPairingTestHooks.PRESENTER_READY_SCHEMA)
                check(request.getBoolean("ready"))
                check(request.getString("payload_sha256") == expectedOfferSha256)
                check(request.getString("marker_file") == InternetPairingTestHooks.FILE_QR_SCAN_MARKER)
                return
            }
            SystemClock.sleep(100)
        }
        throw AssertionError("QR presenter did not become ready within ${timeoutMs}ms")
    }

    private fun completePairing(acceptance: InternetPairingAcceptance) {
        acceptanceStage = "pairing_acceptance_input"
        onView(withHint(R.string.internet_pairing_acceptance_hint))
            .inRoot(RealQrDialogTextRootMatcher(R.string.internet_pairing_complete_title))
            .perform(RealQrSetSensitiveTextAction(acceptance.encode()))
        acceptanceStage = "pairing_acceptance_submit"
        onView(withHint(R.string.internet_pairing_acceptance_hint))
            .inRoot(RealQrDialogTextRootMatcher(R.string.internet_pairing_complete_title))
            .perform(RealQrClickDialogPositiveAction())
        acceptanceStage = "pairing_acceptance_result"
        onView(withId(R.id.internetRevokeButton)).check(matches(isEnabled()))
    }

    private fun importLease(
        scenario: ActivityScenario<MainActivity>,
        encodedLease: String,
    ) {
        acceptanceStage = "lease_import_open"
        scenario.onActivity { activity ->
            check(activity.findViewById<View>(R.id.internetImportProfileButton).performClick()) {
                "Internet profile import action was not handled"
            }
        }
        InstrumentationRegistry.getInstrumentation().waitForIdleSync()
        acceptanceStage = "lease_import_input"
        onView(withHint(R.string.internet_import_hint))
            .inRoot(RealQrDialogTextRootMatcher(R.string.internet_import_title))
            .perform(RealQrSetSensitiveTextAction(encodedLease))
        acceptanceStage = "lease_import_submit"
        onView(withHint(R.string.internet_import_hint))
            .inRoot(RealQrDialogTextRootMatcher(R.string.internet_import_title))
            .perform(RealQrClickDialogPositiveAction())
        acceptanceStage = "lease_import_result"
    }

    private fun revokeThroughUi(scenario: ActivityScenario<MainActivity>) {
        acceptanceStage = "revoke_open"
        scenario.onActivity { activity ->
            check(activity.findViewById<View>(R.id.internetRevokeButton).performClick()) {
                "Internet revoke action was not handled"
            }
        }
        InstrumentationRegistry.getInstrumentation().waitForIdleSync()
        acceptanceStage = "revoke_confirm"
        onView(withId(android.R.id.button1))
            .inRoot(RealQrDialogTextRootMatcher(R.string.internet_revoke_confirm_message))
            .perform(RealQrPerformViewListenerClickAction())
        acceptanceStage = "revoke_result"
        repeat(50) {
            var connectEnabled = true
            scenario.onActivity { activity ->
                connectEnabled = activity.findViewById<View>(R.id.internetConnectButton).isEnabled
            }
            if (!connectEnabled) return
            SystemClock.sleep(100)
        }
        error("Internet connect action remained enabled after revoke")
    }

    private fun cleanupCreatedCredentials(
        context: Context,
        deviceId: String,
        initialIdentityHighWatermark: Long,
        profileStore: InternetSessionProfileStore,
        storedFactory: AndroidStoredInternetSessionFactory,
        revocationCoordinator: InternetProductRevocationCoordinator,
        createdOffers: List<TestPairingOffer>,
        createdLeases: List<Pair<TestPairingOffer, TestLease>>,
    ): Throwable? {
        val failures = mutableListOf<Throwable>()
        val createdPairingIds = createdOffers.map { it.pairingIdentifier }
        fun isCreated(value: String?): Boolean =
            value != null && createdPairingIds.any { MessageDigest.isEqual(it.toByteArray(), value.toByteArray()) }

        runCatching {
            val currentPairing = profileStore.verifiedPairingIdentifier() ?: profileStore.loadPublicProfile()?.pairingIdentifier
            val identityEpoch = profileStore.verifiedLocalIdentityEpoch() ?: profileStore.loadPublicProfile()?.identityEpoch
            if (isCreated(currentPairing) && identityEpoch != null) {
                profileStore.beginRevocationCleanup(checkNotNull(currentPairing), deviceId, identityEpoch)
                val result =
                    profileStore.retryPendingRevocationCleanup(
                        deletePairingSecret = storedFactory::removePairingSecrets,
                        deleteIdentityKey = { ownedDeviceId, epoch -> AndroidDeviceIdentityStore().delete(ownedDeviceId, epoch) },
                    )
                check(result?.remainingSteps.orEmpty().isEmpty()) { "Acceptance revocation cleanup was incomplete" }
            }
        }.onFailure(failures::add)
        runCatching {
            revocationCoordinator.withCredentialMutationAdmission(durableBlock = { false }) { permit ->
                storedFactory.retryPendingPairingPersistenceCleanup(
                    currentPairingIdentifier = createdPairingIds.lastOrNull(),
                    cleanupBusinessState = { pairingId ->
                        if (isCreated(pairingId)) profileStore.removePairingBindingIfMatches(permit, pairingId)
                    },
                )
            }
        }.onFailure(failures::add)
        createdPairingIds.forEach { pairingId ->
            runCatching { storedFactory.removePairingSecrets(pairingId) }.onFailure(failures::add)
        }
        val secretStore = AndroidSecretStore(context)
        createdLeases.forEach { (offer, lease) ->
            runCatching { secretStore.delete(profileSecretSlot(offer, lease)) }.onFailure(failures::add)
        }
        val finalHighWatermark = identityHighWatermark(context)
        if (finalHighWatermark >= initialIdentityHighWatermark && finalHighWatermark - initialIdentityHighWatermark <= 8) {
            (initialIdentityHighWatermark + 1..finalHighWatermark).forEach { epoch ->
                runCatching { AndroidDeviceIdentityStore().delete(deviceId, epoch) }.onFailure(failures::add)
            }
        } else if (finalHighWatermark != initialIdentityHighWatermark) {
            failures += IllegalStateException("Unexpected identity epoch growth")
        }
        return failures.firstOrNull()
    }

    private fun assertSecretsRemoved(
        context: Context,
        offer: TestPairingOffer,
        lease: TestLease,
    ) {
        val store = AndroidSecretStore(context)
        assertTrue(
            "Local revoke retained pairing secrets",
            store.load("phase3.pairing.v1.${sha256(offer.pairingIdentifier.toByteArray()).hex()}") == null,
        )
        assertTrue("Local revoke retained lease secrets", store.load(profileSecretSlot(offer, lease)) == null)
    }
}

private class RealQrDialogTextRootMatcher(
    private val textResource: Int,
) : TypeSafeMatcher<Root>() {
    override fun describeTo(description: Description) {
        description.appendText("the expected production confirmation dialog")
    }

    override fun matchesSafely(root: Root): Boolean {
        val expected = root.decorView.context.getString(textResource)
        return containsText(root.decorView, expected)
    }

    private fun containsText(view: View, expected: String): Boolean {
        if (view is TextView && view.text.toString() == expected) return true
        if (view is ViewGroup) {
            repeat(view.childCount) { index ->
                if (containsText(view.getChildAt(index), expected)) return true
            }
        }
        return false
    }
}

private class RealQrCapturePairingRequestAction(
    private val destination: AtomicReference<String>,
) : ViewAction {
    override fun getConstraints() = allOf(isEnabled())
    override fun getDescription() = "capture protected pairing request without logging it"
    override fun perform(uiController: UiController, view: View) {
        requireSecureWindow(view)
        val encoded = checkNotNull((view as? TextView)?.text?.toString())
        InternetPairingRequest.parse(encoded)
        destination.set(encoded)
        uiController.loopMainThreadUntilIdle()
    }
}

private class RealQrSetSensitiveTextAction(
    private val value: String,
) : ViewAction {
    override fun getConstraints() = allOf(isDisplayed(), isEnabled())
    override fun getDescription() = "enter protected test credential"
    override fun perform(uiController: UiController, view: View) {
        requireSecureWindow(view)
        (view as EditText).setText(value)
        view.setSelection(value.length)
        uiController.loopMainThreadUntilIdle()
    }
}

private class RealQrClickDialogPositiveAction(
    private val requireSecure: Boolean = true,
) : ViewAction {
    override fun getConstraints() = allOf(isDisplayed(), isEnabled())
    override fun getDescription() = "click the positive action in the protected dialog"
    override fun perform(uiController: UiController, view: View) {
        if (requireSecure) requireSecureWindow(view)
        val button = checkNotNull(view.rootView.findViewById<View>(android.R.id.button1))
        check(button.performClick()) { "Protected dialog action was not handled" }
        uiController.loopMainThreadUntilIdle()

        val pairingError = view.rootView.findViewById<TextView>(R.id.internetPairingAcceptanceErrorText)
        if (pairingError != null && pairingError.visibility == View.VISIBLE && !pairingError.text.isNullOrBlank()) {
            error("Protected pairing dialog action failed: ${pairingError.text}")
        }
        val importError = view.rootView.findViewById<TextView>(R.id.internetProfileImportErrorText)
        if (importError != null && importError.visibility == View.VISIBLE && !importError.text.isNullOrBlank()) {
            error("Protected profile import action failed: ${importError.text}")
        }
    }
}

private class RealQrPerformViewListenerClickAction : ViewAction {
    override fun getConstraints() = allOf(isDisplayed(), isEnabled())
    override fun getDescription() = "invoke the matched production view listener"
    override fun perform(uiController: UiController, view: View) {
        check(view.performClick()) { "Matched production view action was not handled" }
        uiController.loopMainThreadUntilIdle()
    }
}

private fun requireSecureWindow(view: View) {
    val parameters = checkNotNull(view.rootView.layoutParams as? WindowManager.LayoutParams)
    check(parameters.flags and WindowManager.LayoutParams.FLAG_SECURE != 0) {
        "Protected dialog is missing FLAG_SECURE"
    }
}

private fun sha256(value: ByteArray): ByteArray = MessageDigest.getInstance("SHA-256").digest(value)
private fun ByteArray.hex(): String = joinToString("") { "%02x".format(it) }
private fun profileSecretSlot(offer: TestPairingOffer, lease: TestLease): String {
    val digest = sha256("${offer.pairingIdentifier}\u0000${lease.signalingSessionId}\u0000${lease.sessionEpoch}".toByteArray()).hex()
    return "phase3.internet.profile.v1.$digest"
}
private fun identityHighWatermark(context: Context): Long =
    context
        .getSharedPreferences("phase3_security_state", Context.MODE_PRIVATE)
        .getLong("identity_epoch_high_watermark", 0)
