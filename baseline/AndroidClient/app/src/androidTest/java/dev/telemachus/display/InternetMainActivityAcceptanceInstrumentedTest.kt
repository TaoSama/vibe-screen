package dev.telemachus.display

import android.Manifest
import android.app.Activity
import android.app.Instrumentation
import android.content.Context
import android.content.Intent
import android.view.View
import android.view.WindowManager
import android.widget.EditText
import android.widget.TextView
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.espresso.Espresso
import androidx.test.espresso.Espresso.onView
import androidx.test.espresso.FailureHandler
import androidx.test.espresso.UiController
import androidx.test.espresso.ViewAction
import androidx.test.espresso.action.ViewActions.click
import androidx.test.espresso.action.ViewActions.scrollTo
import androidx.test.espresso.assertion.ViewAssertions.matches
import androidx.test.espresso.assertion.ViewAssertions.doesNotExist
import androidx.test.espresso.matcher.ViewMatchers.isChecked
import androidx.test.espresso.matcher.ViewMatchers.isDisplayed
import androidx.test.espresso.matcher.ViewMatchers.isEnabled
import androidx.test.espresso.matcher.ViewMatchers.hasErrorText
import androidx.test.espresso.matcher.ViewMatchers.withHint
import androidx.test.espresso.matcher.ViewMatchers.withId
import androidx.test.espresso.matcher.ViewMatchers.withText
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.rule.GrantPermissionRule
import dev.telemachus.display.internet.InternetSessionProfileStore
import dev.telemachus.display.internet.InternetProductRevocationCoordinator
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
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Device-side acceptance for the local Internet credential UI only.
 *
 * The test drives MainActivity and its real AndroidKeyStore-backed pairing/profile stores. It does
 * not open a network connection or claim WebRTC, media capture, decoded video, or remote input.
 * Sensitive wire values stay in memory and are entered with actions whose descriptions never
 * include their payloads, so instrumentation failures do not echo credentials.
 */
@RunWith(AndroidJUnit4::class)
class InternetMainActivityAcceptanceInstrumentedTest {
    @Volatile
    private var acceptanceStage = "initialization"

    @get:Rule
    val cameraPermission: GrantPermissionRule = GrantPermissionRule.grant(Manifest.permission.CAMERA)

    @Test
    fun pairingLeaseRevokeAndRepairAreAcceptedThroughMainActivity() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = ApplicationProvider.getApplicationContext<Context>()
        val profileStore = InternetSessionProfileStore(context)
        val preferences = PreferencesManager(context)
        val deviceId = preferences.internetDeviceId
        val storedFactory = AndroidStoredInternetSessionFactory(context, deviceId)
        val revocationCoordinator = InternetProductRevocationCoordinator.processShared()
        Espresso.setFailureHandler(
            FailureHandler { _, _ -> throw AssertionError("Protected Internet UI action failed at $acceptanceStage") },
        )
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

        var primaryFailure: Throwable? = null
        try {
            ActivityScenario.launch(MainActivity::class.java).use { scenario ->
                acceptanceStage = "internet_tab"
                onView(withId(R.id.modeInternet)).perform(click())
                onView(withId(R.id.internetModeContent)).check(matches(isDisplayed()))
                acceptanceStage = "route_toggle"
                onView(withId(R.id.internetPreferDirect)).check(matches(isChecked()))
                onView(withId(R.id.internetForceRelay)).perform(click())
                assertTrue(PreferencesManager(context).internetForceRelay)
                onView(withId(R.id.internetPreferDirect)).perform(click())
                assertFalse(PreferencesManager(context).internetForceRelay)

                val firstOffer = authority.createOffer().also(createdOffers::add)
                acceptanceStage = "first_pairing_scan"
                val firstRequest = scanAndCaptureRequest(instrumentation, firstOffer.encodedUrl)
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

                val staleLease = authority.issueLease(firstOffer, firstRequest, firstEpoch - 1)
                acceptanceStage = "stale_lease_rejection"
                importLease(scenario, staleLease.encoded)
                onView(withHint(R.string.internet_import_hint))
                    .check(matches(hasErrorText("A replacement Internet lease must use a strictly newer session epoch")))
                assertEquals(
                    "Stale lease replaced the authoritative session epoch",
                    firstEpoch,
                    profileStore.loadPublicProfile()?.authoritativeSessionEpoch,
                )
                onView(withHint(R.string.internet_import_hint)).perform(ClickDialogNegativeAction())
                onView(withHint(R.string.internet_import_hint)).check(doesNotExist())

                acceptanceStage = "first_revoke"
                revokeThroughUi(scenario)
                assertTrue("Local revoke retained a profile", profileStore.loadPublicProfile() == null)
                assertFalse(profileStore.hasVerifiedPairing())
                assertSecretsRemoved(context, firstOffer, firstLease)

                val secondOffer = authority.createOffer().also(createdOffers::add)
                acceptanceStage = "second_pairing_scan"
                val secondRequest = scanAndCaptureRequest(instrumentation, secondOffer.encodedUrl)
                acceptanceStage = "second_pairing_acceptance"
                completePairing(authority.accept(secondOffer, secondRequest))
                val secondLease = authority.issueLease(secondOffer, secondRequest, firstEpoch + 1)
                createdLeases += secondOffer to secondLease
                acceptanceStage = "second_lease_import"
                importLease(scenario, secondLease.encoded)

                assertTrue(profileStore.hasVerifiedPairing())
                assertTrue(
                    "Re-pair did not bind the fresh pairing",
                    profileStore.verifiedPairingIdentifier()?.let {
                        MessageDigest.isEqual(secondOffer.pairingIdentifier.toByteArray(), it.toByteArray())
                    } == true,
                )
                assertEquals(firstEpoch + 1, profileStore.loadPublicProfile()?.authoritativeSessionEpoch)
                onView(withId(R.id.internetConnectButton)).check(matches(isEnabled()))

                // Leave the dedicated acceptance installation clean for a repeat run.
                acceptanceStage = "second_revoke"
                revokeThroughUi(scenario)
                assertSecretsRemoved(context, secondOffer, secondLease)
            }
        } catch (failure: Throwable) {
            primaryFailure = failure
            throw failure
        } finally {
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
            "PHASE3_ANDROID_INTERNET_UI_PASS internet_tab=true route_toggle=true " +
                "pairing=true strict_lease_import=true local_revoke=true repair=true secure_dialogs=true",
        )
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

    private fun scanAndCaptureRequest(
        instrumentation: Instrumentation,
        encodedOffer: String,
    ): InternetPairingRequest {
        val result = Intent().putExtra(QRScannerActivity.EXTRA_URL, encodedOffer)
        val monitor =
            instrumentation.addMonitor(
                QRScannerActivity::class.java.name,
                Instrumentation.ActivityResult(Activity.RESULT_OK, result),
                true,
            )
        try {
            onView(withId(R.id.internetScanProfileButton)).perform(scrollTo(), click())
            instrumentation.waitForIdleSync()

            val request = AtomicReference<String>()
            onView(PairingRequestViewMatcher())
                .perform(CaptureSensitiveTextAction(request))
            assertEquals("The pairing scanner result was not consumed", 1, monitor.hits)
            return InternetPairingRequest.parse(checkNotNull(request.get()))
        } finally {
            instrumentation.removeMonitor(monitor)
        }
    }

    private fun completePairing(acceptance: InternetPairingAcceptance) {
        acceptanceStage = "pairing_acceptance_input"
        onView(withHint(R.string.internet_pairing_acceptance_hint))
            .perform(SetSensitiveTextAction(acceptance.encode()))
        acceptanceStage = "pairing_acceptance_submit"
        onView(withHint(R.string.internet_pairing_acceptance_hint))
            .perform(ClickDialogPositiveAction())
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
            .perform(SetSensitiveTextAction(encodedLease))
        acceptanceStage = "lease_import_submit"
        onView(withHint(R.string.internet_import_hint))
            .perform(ClickDialogPositiveAction())
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
        onView(withText(R.string.internet_revoke_confirm_message))
            .perform(ClickDialogPositiveAction(requireSecure = false))
        acceptanceStage = "revoke_result"
        onView(withId(R.id.internetConnectButton)).check(matches(not(isEnabled())))
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

private class PairingRequestViewMatcher : TypeSafeMatcher<View>() {
    override fun describeTo(description: Description) {
        description.appendText("protected pairing request text")
    }

    override fun matchesSafely(view: View): Boolean =
        view is TextView && runCatching { InternetPairingRequest.parse(view.text.toString()) }.isSuccess
}

private class CaptureSensitiveTextAction(
    private val destination: AtomicReference<String>,
) : ViewAction {
    override fun getConstraints() = allOf(isDisplayed())
    override fun getDescription() = "capture protected text without logging it"
    override fun perform(uiController: UiController, view: View) {
        requireSecureWindow(view)
        destination.set((view as TextView).text.toString())
        uiController.loopMainThreadUntilIdle()
    }
}

private class SetSensitiveTextAction(
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

private class ClickDialogPositiveAction(
    private val requireSecure: Boolean = true,
) : ViewAction {
    override fun getConstraints() = allOf(isDisplayed(), isEnabled())
    override fun getDescription() = "click the positive action in the protected dialog"
    override fun perform(uiController: UiController, view: View) {
        if (requireSecure) requireSecureWindow(view)
        val button = checkNotNull(view.rootView.findViewById<View>(android.R.id.button1))
        check(button.performClick()) { "Protected dialog action was not handled" }
        uiController.loopMainThreadUntilIdle()
    }
}

private class ClickDialogNegativeAction : ViewAction {
    override fun getConstraints() = allOf(isDisplayed(), isEnabled())
    override fun getDescription() = "dismiss the protected dialog"
    override fun perform(uiController: UiController, view: View) {
        requireSecureWindow(view)
        val button = checkNotNull(view.rootView.findViewById<View>(android.R.id.button2))
        check(button.performClick()) { "Protected dialog dismiss action was not handled" }
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
