package dev.telemachus.display

import android.app.Activity
import android.app.Instrumentation
import android.content.Context
import android.content.Intent
import android.os.SystemClock
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.EditText
import android.widget.TextView
import com.google.gson.JsonParser
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.espresso.Espresso
import androidx.test.espresso.Espresso.onView
import androidx.test.espresso.FailureHandler
import androidx.test.espresso.Root
import androidx.test.espresso.UiController
import androidx.test.espresso.ViewAction
import androidx.test.espresso.action.ViewActions.click
import androidx.test.espresso.assertion.ViewAssertions.matches
import androidx.test.espresso.base.DefaultFailureHandler
import androidx.test.espresso.matcher.ViewMatchers.isChecked
import androidx.test.espresso.matcher.ViewMatchers.isDisplayed
import androidx.test.espresso.matcher.ViewMatchers.isEnabled
import androidx.test.espresso.matcher.ViewMatchers.withContentDescription
import androidx.test.espresso.matcher.ViewMatchers.withHint
import androidx.test.espresso.matcher.ViewMatchers.withId
import androidx.test.espresso.matcher.ViewMatchers.withText
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.lifecycle.Lifecycle
import dev.telemachus.display.internet.InternetSessionProfileStore
import dev.telemachus.display.internet.InternetProductRevocationCoordinator
import dev.telemachus.display.internet.security.AndroidDeviceIdentityStore
import dev.telemachus.display.internet.security.AndroidSecretStore
import dev.telemachus.display.internet.security.AndroidStoredInternetSessionFactory
import dev.telemachus.display.internet.security.AndroidDeviceIdentityPairingSigner
import dev.telemachus.display.internet.security.InternetPairingCoordinator
import dev.telemachus.display.internet.security.InternetPairingAcceptance
import dev.telemachus.display.internet.security.InternetPairingRequest
import java.security.MessageDigest
import java.util.concurrent.atomic.AtomicReference
import org.hamcrest.Description
import org.hamcrest.Matchers.allOf
import org.hamcrest.Matchers.containsString
import org.hamcrest.Matchers.not
import org.hamcrest.TypeSafeMatcher
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.Assume.assumeTrue
import org.junit.rules.RuleChain
import org.junit.rules.TestRule
import org.junit.runner.RunWith
import org.junit.runners.model.Statement

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

    private val optInRule =
        TestRule { base, _ ->
            object : Statement() {
                override fun evaluate() {
                    val arguments = InstrumentationRegistry.getArguments()
                    assumeTrue(
                        "Pass a dedicated Android-local Internet UI acceptance opt-in only from the evidence runner",
                        arguments.getString(BOOTSTRAP_OPT_IN_ARGUMENT, "false").toBoolean() ||
                            arguments.getString(EXPIRED_LEASE_UX_OPT_IN_ARGUMENT, "false").toBoolean(),
                    )
                    base.evaluate()
                }
            }
        }
    @get:Rule
    val acceptanceRules: RuleChain = RuleChain.outerRule(optInRule)

    @After
    fun restoreDefaultEspressoFailureHandler() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        Espresso.setFailureHandler(DefaultFailureHandler(context))
        acceptanceStage = "initialization"
    }

    @Test
    fun pairingLeaseRevokeAndRepairAreAcceptedThroughMainActivity() {
        assumeTrue(
            "Pass -e $BOOTSTRAP_OPT_IN_ARGUMENT true only from the dedicated Android-local Internet UI/bootstrap runner",
            InstrumentationRegistry.getArguments().getString(BOOTSTRAP_OPT_IN_ARGUMENT, "false").toBoolean(),
        )
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = ApplicationProvider.getApplicationContext<Context>()
        val profileStore = InternetSessionProfileStore(context)
        val preferences = PreferencesManager(context)
        val deviceId = preferences.internetDeviceId
        val storedFactory = AndroidStoredInternetSessionFactory(context, deviceId)
        val revocationCoordinator = InternetProductRevocationCoordinator.processShared()
        Espresso.setFailureHandler(
            FailureHandler { failure, _ ->
                throw AssertionError(
                    "Protected Internet UI action failed at $acceptanceStage (${failure.javaClass.simpleName})",
                )
            },
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
        val firstEpoch = 1L

        var primaryFailure: Throwable? = null
        try {
            ActivityScenario.launch(MainActivity::class.java).use { scenario ->
                acceptanceStage = "internet_tab"
                onView(withId(R.id.modeInternet)).perform(click())
                onView(withId(R.id.internetModeContent)).check(matches(isDisplayed()))
                onView(withId(R.id.internetRevokeButton)).check(matches(not(isDisplayed())))
                acceptanceStage = "route_toggle"
                onView(withId(R.id.internetPreferDirect)).check(matches(isChecked()))
                onView(withId(R.id.internetForceRelay)).perform(click())
                assertTrue(PreferencesManager(context).internetForceRelay)
                onView(withId(R.id.internetPreferDirect)).perform(click())
                assertFalse(PreferencesManager(context).internetForceRelay)

                val firstOffer = authority.createOffer().also(createdOffers::add)
                acceptanceStage = "first_pairing_scan"
                val firstRequest = scanAndCaptureRequest(scenario, instrumentation, firstOffer.encodedUrl)
                acceptanceStage = "first_pairing_acceptance"
                completePairing(authority.accept(firstOffer, firstRequest))
                assertTrue(profileStore.hasVerifiedPairing())
                onView(withId(R.id.internetConnectButton)).check(matches(not(isEnabled())))
                onView(withId(R.id.internetRevokeButton)).check(matches(isDisplayed()))

                val firstLease = authority.issueLease(firstOffer, firstRequest, firstEpoch)
                createdLeases += firstOffer to firstLease
                acceptanceStage = "first_lease_import_after_rejected_draft"
                importLeaseAfterRejectedDraft(scenario, firstLease.encoded)
                assertEquals(firstEpoch, profileStore.loadPublicProfile()?.authoritativeSessionEpoch)
                onView(withId(R.id.internetConnectButton)).check(matches(isEnabled()))

                acceptanceStage = "first_revoke"
                revokeThroughUi(scenario)
                assertTrue("Local revoke retained a profile", profileStore.loadPublicProfile() == null)
                assertFalse(profileStore.hasVerifiedPairing())
                onView(withId(R.id.internetRevokeButton)).check(matches(not(isDisplayed())))
                assertSecretsRemoved(context, firstOffer, firstLease)

                val secondOffer = authority.createOffer().also(createdOffers::add)
                acceptanceStage = "second_pairing_scan"
                val secondRequest = scanAndCaptureRequest(scenario, instrumentation, secondOffer.encodedUrl)
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
                onView(withId(R.id.internetRevokeButton)).check(matches(isDisplayed()))

                // Leave the dedicated acceptance installation clean for a repeat run.
                acceptanceStage = "second_revoke"
                revokeThroughUi(scenario)
                onView(withId(R.id.internetRevokeButton)).check(matches(not(isDisplayed())))
                assertSecretsRemoved(context, secondOffer, secondLease)
            }
        } catch (failure: AssertionError) {
            primaryFailure = failure
            throw failure
        } catch (failure: RuntimeException) {
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
                "pairing=true strict_lease_import=true retryable_import_error=true " +
                "local_revoke=true repair=true secure_dialogs=true",
        )
    }

    @Test
    fun expiredStoredLeaseDisablesConnectAcrossForegroundAndRecreation() {
        assumeTrue(
            "Pass -e $EXPIRED_LEASE_UX_OPT_IN_ARGUMENT true only from the dedicated Android-local expired-lease UX runner",
            InstrumentationRegistry.getArguments().getString(EXPIRED_LEASE_UX_OPT_IN_ARGUMENT, "false").toBoolean(),
        )
        val context = ApplicationProvider.getApplicationContext<Context>()
        val profileStore = InternetSessionProfileStore(context)
        val preferences = PreferencesManager(context)
        val deviceId = preferences.internetDeviceId
        val storedFactory = AndroidStoredInternetSessionFactory(context, deviceId)
        val revocationCoordinator = InternetProductRevocationCoordinator.processShared()
        Espresso.setFailureHandler(
            FailureHandler { failure, _ ->
                throw AssertionError(
                    "Protected Internet expired-lease UX action failed at $acceptanceStage (${failure.javaClass.simpleName})",
                )
            },
        )
        assertTrue("Expired-lease UX acceptance requires a clean profile store", profileStore.loadPublicProfile() == null)
        assertFalse("Expired-lease UX acceptance requires a clean pairing store", profileStore.hasVerifiedPairing())

        preferences.apply {
            connectionMode = ConnectionMode.USB
            internetForceRelay = false
        }
        val initialIdentityHighWatermark = identityHighWatermark(context)
        val createdOffers = mutableListOf<TestPairingOffer>()
        val createdLeases = mutableListOf<Pair<TestPairingOffer, TestLease>>()
        val authority = TestHostAuthority()
        val firstEpoch = 1L

        var primaryFailure: Throwable? = null
        try {
            ActivityScenario.launch(MainActivity::class.java).use { scenario ->
                acceptanceStage = "expired_lease_internet_tab"
                onView(withId(R.id.modeInternet)).perform(click())
                onView(withId(R.id.internetModeContent)).check(matches(isDisplayed()))

                val offer = authority.createOffer().also(createdOffers::add)
                acceptanceStage = "lease_expiry_pairing_store"
                val request = completePairingWithoutCameraPermission(
                    context = context,
                    offer = offer,
                    authority = authority,
                    profileStore = profileStore,
                    storedFactory = storedFactory,
                    revocationCoordinator = revocationCoordinator,
                )

                val firstLease = authority.issueLease(offer, request, firstEpoch)
                createdLeases += offer to firstLease
                acceptanceStage = "expired_lease_fresh_import"
                importLease(scenario, firstLease.encoded)
                onView(withId(R.id.internetConnectButton)).check(matches(isEnabled()))

                acceptanceStage = "stale_lease_foreground_refresh"
                scenario.onActivity { activity ->
                    markFreshLeaseRequiredForAcceptance(activity, firstEpoch)
                }
                assertStaleLeaseUi(firstEpoch)

                scenario.moveToState(Lifecycle.State.CREATED)
                scenario.moveToState(Lifecycle.State.RESUMED)
                assertStaleLeaseUi(firstEpoch)

                val staleReplacementLease = authority.issueLease(offer, request, firstEpoch + 1)
                createdLeases += offer to staleReplacementLease
                acceptanceStage = "stale_lease_replacement_import"
                importLease(scenario, staleReplacementLease.encoded)
                assertEquals(firstEpoch + 1, profileStore.loadPublicProfile()?.authoritativeSessionEpoch)
                onView(withId(R.id.internetConnectButton)).check(matches(isEnabled()))

                scenario.moveToState(Lifecycle.State.CREATED)
                expirePersistedProfile(context, expiresAtUnixSeconds = System.currentTimeMillis() / 1_000)
                acceptanceStage = "expired_lease_foreground_refresh"
                scenario.moveToState(Lifecycle.State.RESUMED)
                assertExpiredLeaseUi()

                acceptanceStage = "expired_lease_recreation_refresh"
                scenario.recreate()
                assertExpiredLeaseUi()

                val replacementLease = authority.issueLease(offer, request, firstEpoch + 2)
                createdLeases += offer to replacementLease
                acceptanceStage = "expired_lease_replacement_import"
                importLease(scenario, replacementLease.encoded)
                assertEquals(firstEpoch + 2, profileStore.loadPublicProfile()?.authoritativeSessionEpoch)
                onView(withId(R.id.internetConnectButton)).check(matches(isEnabled()))

                acceptanceStage = "expired_lease_cleanup_revoke"
                revokeThroughUi(scenario)
                onView(withId(R.id.internetRevokeButton)).check(matches(not(isDisplayed())))
                assertSecretsRemoved(context, offer, firstLease)
                assertSecretsRemoved(context, offer, staleReplacementLease)
                assertSecretsRemoved(context, offer, replacementLease)
            }
        } catch (failure: AssertionError) {
            primaryFailure = failure
            throw failure
        } catch (failure: RuntimeException) {
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
                val redacted = AssertionError("Expired-lease UX credential cleanup was incomplete")
                if (primaryFailure == null) throw redacted else primaryFailure.addSuppressed(redacted)
            }
        }

        println(
            "PHASE3_ANDROID_INTERNET_EXPIRED_STALE_LEASE_UX_PASS " +
                "expired_summary=true stale_summary=true connect_disabled=true " +
                "stale_foreground_refresh=true expired_foreground_refresh=true " +
                "expired_recreation_refresh=true fresh_reimport=true " +
                "scan_import_revoke_available=true android_local_only=true",
        )
    }

    private fun completePairingWithoutCameraPermission(
        context: Context,
        offer: TestPairingOffer,
        authority: TestHostAuthority,
        profileStore: InternetSessionProfileStore,
        storedFactory: AndroidStoredInternetSessionFactory,
        revocationCoordinator: InternetProductRevocationCoordinator,
    ): InternetPairingRequest {
        val identityEpoch = storedFactory.reserveNextIdentityEpoch()
        val identityStore = AndroidDeviceIdentityStore()
        val identity = identityStore.loadOrCreateForPairing(deviceId = PreferencesManager(context).internetDeviceId, identityEpoch)
        val pending = InternetPairingCoordinator(
            signer = AndroidDeviceIdentityPairingSigner(identity),
            secretSink = storedFactory.internetPairingSecretSinkForAcceptance(),
        ).begin(offer.encodedUrl, "P0110")
        try {
            revocationCoordinator.withCredentialMutationAdmission(
                durableBlock = {
                    profileStore.hasDurableCredentialMutationBlock(offer.pairingIdentifier) ||
                        storedFactory.hasPendingPairingPersistenceCleanup()
                },
            ) { permit ->
                val result = pending.complete(authority.accept(offer, pending.request))
                profileStore.recordVerifiedPairing(permit, result.metadata, storedFactory)
            }
            return pending.request
        } finally {
            pending.close()
        }
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
        scenario: ActivityScenario<MainActivity>,
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
            scenario.onActivity { activity ->
                check(activity.findViewById<View>(R.id.internetScanProfileButton).performClick()) {
                    "Internet pairing scan action was not handled"
                }
            }
            instrumentation.waitForIdleSync()

            val request = AtomicReference<String>()
            onView(withHint(R.string.internet_pairing_acceptance_hint))
                .inRoot(DialogTextRootMatcher(R.string.internet_pairing_complete_title))
                .perform(CapturePairingRequestFromDialogAction(request))
            assertEquals("The pairing scanner result was not consumed", 1, monitor.hits)
            return InternetPairingRequest.parse(checkNotNull(request.get()))
        } finally {
            instrumentation.removeMonitor(monitor)
        }
    }

    private fun completePairing(acceptance: InternetPairingAcceptance) {
        acceptanceStage = "pairing_acceptance_input"
        onView(withHint(R.string.internet_pairing_acceptance_hint))
            .inRoot(DialogTextRootMatcher(R.string.internet_pairing_complete_title))
            .perform(SetSensitiveTextAction(acceptance.encode()))
        acceptanceStage = "pairing_acceptance_submit"
        onView(withHint(R.string.internet_pairing_acceptance_hint))
            .inRoot(DialogTextRootMatcher(R.string.internet_pairing_complete_title))
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
            .inRoot(DialogTextRootMatcher(R.string.internet_import_title))
            .perform(SetSensitiveTextAction(encodedLease))
        acceptanceStage = "lease_import_submit"
        onView(withHint(R.string.internet_import_hint))
            .inRoot(DialogTextRootMatcher(R.string.internet_import_title))
            .perform(ClickDialogPositiveAction())
        acceptanceStage = "lease_import_result"
    }

    private fun importLeaseAfterRejectedDraft(
        scenario: ActivityScenario<MainActivity>,
        encodedLease: String,
    ) {
        val context = ApplicationProvider.getApplicationContext<Context>()
        acceptanceStage = "lease_import_open"
        scenario.onActivity { activity ->
            check(activity.findViewById<View>(R.id.internetImportProfileButton).performClick()) {
                "Internet profile import action was not handled"
            }
        }
        InstrumentationRegistry.getInstrumentation().waitForIdleSync()
        acceptanceStage = "lease_import_rejected_draft_input"
        onView(withHint(R.string.internet_import_hint))
            .inRoot(DialogTextRootMatcher(R.string.internet_import_title))
            .perform(SetSensitiveTextAction(INVALID_LEASE_JSON))
        acceptanceStage = "lease_import_rejected_draft_submit"
        onView(withHint(R.string.internet_import_hint))
            .inRoot(DialogTextRootMatcher(R.string.internet_import_title))
            .perform(ClickDialogPositiveAction(expectDialogError = true))
        acceptanceStage = "lease_import_rejected_draft_result"
        onView(withId(R.id.internetProfileImportErrorText))
            .inRoot(DialogTextRootMatcher(R.string.internet_import_title))
            .check(matches(isDisplayed()))
        assertTrue("Rejected draft must not persist a profile", InternetSessionProfileStore(context).loadPublicProfile() == null)

        acceptanceStage = "lease_import_corrected_input"
        onView(withHint(R.string.internet_import_hint))
            .inRoot(DialogTextRootMatcher(R.string.internet_import_title))
            .perform(SetSensitiveTextAction(encodedLease))
        onView(withId(R.id.internetProfileImportErrorText))
            .inRoot(DialogTextRootMatcher(R.string.internet_import_title))
            .check(matches(not(isDisplayed())))
        acceptanceStage = "lease_import_corrected_submit"
        onView(withHint(R.string.internet_import_hint))
            .inRoot(DialogTextRootMatcher(R.string.internet_import_title))
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
        onView(withId(android.R.id.button1))
            .inRoot(DialogTextRootMatcher(R.string.internet_revoke_confirm_message))
            .perform(PerformViewListenerClickAction())
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

    private fun expirePersistedProfile(
        context: Context,
        expiresAtUnixSeconds: Long,
    ) {
        val preferences = context.getSharedPreferences(INTERNET_PROFILE_PREFERENCES, Context.MODE_PRIVATE)
        val raw = requireNotNull(preferences.getString(InternetSessionProfileStore.PROFILE_KEY, null))
        val root = JsonParser.parseString(raw).asJsonObject.apply {
            addProperty("expires_at", expiresAtUnixSeconds)
        }
        check(
            preferences
                .edit()
                .putString(InternetSessionProfileStore.PROFILE_KEY, root.toString())
                .commit(),
        ) { "Could not persist expired public Internet profile" }
    }

    private fun assertExpiredLeaseUi() {
        onView(withId(R.id.internetProfileSummary))
            .check(matches(withText(containsString("Expired session"))))
        assertUnavailableLeaseActionsRemainAvailable()
    }

    private fun assertStaleLeaseUi(epoch: Long) {
        onView(withId(R.id.internetProfileSummary))
            .check(matches(withText(containsString("Stale session"))))
        onView(withId(R.id.internetProfileSummary))
            .check(matches(withText(containsString("epoch $epoch"))))
        assertUnavailableLeaseActionsRemainAvailable()
    }

    private fun markFreshLeaseRequiredForAcceptance(
        activity: MainActivity,
        sessionEpoch: Long,
    ) {
        val coordinator = activity.javaClass.getDeclaredField("productSessionCoordinator").apply { isAccessible = true }.get(activity)
        val generation = coordinator.javaClass.getDeclaredMethod("currentInternetGeneration").invoke(coordinator) as Long
        val marked =
            coordinator.javaClass
                .getDeclaredMethod("markInternetSessionStartFailed", Long::class.javaPrimitiveType, Long::class.javaPrimitiveType)
                .invoke(coordinator, generation, sessionEpoch) as Boolean
        check(marked) { "Could not mark stale Internet lease epoch" }
        activity.javaClass.getDeclaredMethod("refreshInternetProfileUi").apply { isAccessible = true }.invoke(activity)
    }

    private fun assertUnavailableLeaseActionsRemainAvailable() {
        onView(withId(R.id.internetConnectButton))
            .check(matches(not(isEnabled())))
        onView(withId(R.id.internetConnectButton))
            .check(matches(withContentDescription(R.string.internet_connect_fresh_profile_required_description)))
        onView(withId(R.id.internetImportProfileButton)).check(matches(isEnabled()))
        onView(withId(R.id.internetScanProfileButton)).check(matches(isEnabled()))
        onView(withId(R.id.internetRevokeButton)).check(matches(isEnabled()))
    }
}

private class DialogTextRootMatcher(
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

private class CapturePairingRequestFromDialogAction(
    private val destination: AtomicReference<String>,
) : ViewAction {
    override fun getConstraints() = allOf(isEnabled())
    override fun getDescription() = "capture protected pairing request without logging it"
    override fun perform(uiController: UiController, view: View) {
        requireSecureWindow(view)
        destination.set(checkNotNull(findPairingRequest(view.rootView)))
        uiController.loopMainThreadUntilIdle()
    }

    private fun findPairingRequest(view: View): String? {
        if (view is TextView && runCatching { InternetPairingRequest.parse(view.text.toString()) }.isSuccess) {
            return view.text.toString()
        }
        if (view is ViewGroup) {
            repeat(view.childCount) { index ->
                findPairingRequest(view.getChildAt(index))?.let { return it }
            }
        }
        return null
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
    private val expectDialogError: Boolean = false,
) : ViewAction {
    override fun getConstraints() = allOf(isDisplayed(), isEnabled())
    override fun getDescription() = "click the positive action in the protected dialog"
    override fun perform(uiController: UiController, view: View) {
        if (requireSecure) requireSecureWindow(view)
        val button = checkNotNull(view.rootView.findViewById<View>(android.R.id.button1))
        check(button.performClick()) { "Protected dialog action was not handled" }
        uiController.loopMainThreadUntilIdle()
        if (expectDialogError) {
            check((view as? EditText)?.error != null) {
                "Protected dialog action did not expose the expected retryable error"
            }
            return
        }
        check((view as? EditText)?.error == null) {
            "Protected dialog action failed: ${(view as EditText).error}"
        }
    }
}

private class PerformViewListenerClickAction : ViewAction {
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
private fun AndroidStoredInternetSessionFactory.internetPairingSecretSinkForAcceptance() =
    dev.telemachus.display.internet.security.InternetPairingSecretSink(::persistPairingSecrets)
private fun identityHighWatermark(context: Context): Long =
    context
        .getSharedPreferences("phase3_security_state", Context.MODE_PRIVATE)
        .getLong("identity_epoch_high_watermark", 0)

private const val BOOTSTRAP_OPT_IN_ARGUMENT = "vibeScreenInternetUiBootstrapAcceptance"
private const val EXPIRED_LEASE_UX_OPT_IN_ARGUMENT = "vibeScreenInternetExpiredLeaseUxAcceptance"
private const val INTERNET_PROFILE_PREFERENCES = "phase3_internet_profile"
private const val INVALID_LEASE_JSON = "{\"version\":1,\"invalid\":true}"
