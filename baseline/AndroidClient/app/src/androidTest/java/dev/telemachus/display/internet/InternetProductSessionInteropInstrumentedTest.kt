package dev.telemachus.display.internet

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import dev.telemachus.display.internet.security.AndroidStoredInternetSessionFactory
import dev.telemachus.display.internet.security.AndroidSessionSecurity
import dev.telemachus.display.internet.security.AndroidDeviceIdentityPairingSigner
import dev.telemachus.display.internet.security.AndroidDeviceIdentityStore
import dev.telemachus.display.internet.security.DurableSecurityState
import dev.telemachus.display.internet.security.SecurityStateStore
import dev.telemachus.display.internet.security.TrafficKeyDerivation
import java.io.File
import java.util.Base64
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Real Android M144 endpoint paired with the Mac M150 external-host harness. */
@RunWith(AndroidJUnit4::class)
class InternetProductSessionInteropInstrumentedTest {
    @Test
    fun realProductSessionInteroperatesWithMacHost() {
        val arguments = Arguments(InstrumentationRegistry.getArguments())
        val context = ApplicationProvider.getApplicationContext<Context>()
        val secretFile = arguments.privateConfigFile(context)
        val secrets = SecretConfiguration.readAndDelete(secretFile)
        val sharedSecret = secrets.sharedSecret
        val bootstrapSecret = secrets.bootstrapSecret
        val transcriptContext = secrets.transcriptContext
        val epoch = secrets.sessionEpoch
        val forceRelay = arguments.boolean("forceRelay")
        val expectedRoute = if (forceRelay) PeerRoute.RELAY else PeerRoute.DIRECT
        val localDeviceId = secrets.deviceId
        val hostId = secrets.hostId
        val sessionId = secrets.sessionId
        val pairingId = "interop-$sessionId"
        val storedFactory =
            AndroidStoredInternetSessionFactory(
                context,
                localDeviceId,
                sessionSecurity =
                    AndroidSessionSecurity(
                        localDeviceId,
                        context,
                        stateStore = InteropSecurityStateStore(),
                    ),
            )
        val identityEpoch = storedFactory.reserveNextIdentityEpoch()
        val localIdentity =
            AndroidDeviceIdentityPairingSigner(
                AndroidDeviceIdentityStore().loadOrCreateForPairing(localDeviceId, identityEpoch),
            ).publicIdentity
        val lease =
            InternetProductSessionLease(
                pairingIdentifier = pairingId,
                signalingSessionId = sessionId,
                authoritativeSessionEpoch = epoch,
                identityEpoch = identityEpoch,
                localIdentity = localIdentity,
                transcriptContext = transcriptContext,
                iceServers =
                    listOf(
                        IceServer(
                            secrets.iceUrls,
                            secrets.iceUsername,
                            secrets.iceCredential,
                        ),
                    ),
                signaling =
                    SignalingConfiguration(
                        baseUrl = secrets.signalingUrl,
                        bearerToken = secrets.deviceToken,
                        role = PeerRole.DEVICE,
                        allowInsecureForTesting = secrets.allowInsecureSignaling,
                    ),
                pinnedHostId = hostId,
                iceTransportPolicy = if (forceRelay) IceTransportPolicy.RELAY_ONLY else IceTransportPolicy.ALL,
            )
        val boundContext = lease.boundTranscriptContext(localDeviceId)
        assertEquals(secrets.expectedBoundContextHex, boundContext.hex())
        val keys = TrafficKeyDerivation.initial(sharedSecret, bootstrapSecret, boundContext)
        try {
            assertEquals(secrets.expectedTrafficKeyId, keys.keyId)
        } finally {
            keys.close()
        }

        val revocationCoordinator = InternetProductRevocationCoordinator()
        var pairingPersistenceCompleted = false
        var pairingPersistenceFailure: Throwable? = null
        try {
            revocationCoordinator.withCredentialMutationAdmission(durableBlock = { false }) {
                storedFactory.persistPairingSecrets(pairingId, sharedSecret, bootstrapSecret)
                storedFactory.completePairingPersistence(
                    pairingId,
                    commitBusinessState = { storedFactory.authorizeIdentity(localIdentity) },
                    cleanupBusinessState = {},
                )
                pairingPersistenceCompleted = true
            }
        } catch (failure: Throwable) {
            pairingPersistenceFailure = failure
            throw failure
        } finally {
            val cleanupFailure =
                if (pairingPersistenceCompleted) null else cleanupInteropPairing(storedFactory, revocationCoordinator, pairingId)
            sharedSecret.fill(0)
            bootstrapSecret.fill(0)
            if (cleanupFailure != null) {
                val redacted = AssertionError("Interop pairing persistence cleanup was incomplete")
                if (pairingPersistenceFailure == null) throw redacted else pairingPersistenceFailure.addSuppressed(redacted)
            }
        }
        val sessionReference = AtomicReference<InternetProductSession?>()
        val active = CountDownLatch(1)
        val configured = CountDownLatch(1)
        val keyframe = CountDownLatch(1)
        val delta = CountDownLatch(1)
        val touchSent = CountDownLatch(1)
        val routeSelected = CountDownLatch(1)
        val failures = mutableListOf<Throwable>()
        val selectedRoute = AtomicReference<PeerRoute?>()
        val callbacks =
            object : InternetProductSessionCallbacks {
                override fun onStateChanged(state: InternetProductSessionState) {
                    if (state == InternetProductSessionState.ACTIVE) active.countDown()
                }

                override fun onRouteSelected(route: PeerRoute) {
                    selectedRoute.set(route)
                    routeSelected.countDown()
                }

                override fun onVideoConfiguration(
                    configuration: ProductVideoConfiguration,
                    effect: ProductVideoConfigurationEffect,
                    completion: (ProductVideoDecision) -> Unit,
                ) {
                    completion(
                        effect.commit {
                            assertEquals(ProductVideoCodec.HEVC, configuration.codec)
                            assertEquals(1L, configuration.configEpoch)
                            assertEquals(1L, configuration.streamId)
                            assertEquals(1_920, configuration.width)
                            assertEquals(1_080, configuration.height)
                            configured.countDown()
                            ProductVideoDecision.ACCEPT
                        },
                    )
                }

                override fun onVideoFrame(frame: ProductVideoFrame) {
                    when {
                        frame.keyframe && frame.payload.contentEquals(KEYFRAME) -> {
                            keyframe.countDown()
                            sessionReference.get()?.requestKeyframe("interop_keyframe_received")
                        }
                        !frame.keyframe && frame.payload.contentEquals(DELTA) -> {
                            delta.countDown()
                            if (
                                sessionReference.get()?.sendTouch(
                                    ProductTouchEvent(41, 1, ProductInputPhase.BEGAN, 0.25, 0.75),
                                ) == true
                            ) {
                                touchSent.countDown()
                            }
                        }
                    }
                }

                override fun onFailure(error: Throwable) {
                    synchronized(failures) { failures += error }
                }
            }
        val session =
            try {
                InternetProductSession.create(
                    storedSessionFactory = storedFactory,
                    localDeviceId = localDeviceId,
                    lease = lease,
                    networkMonitor = AndroidNetworkMonitor(context),
                    clock = MonotonicClock { android.os.SystemClock.elapsedRealtime() },
                    codec = ProtobufProtocolV1ProductCodec(localDeviceId, "Android M144 interop", setOf(ProductVideoCodec.HEVC)),
                    callbacks = callbacks,
                    revocationStore =
                        object : InternetProductRevocationStore {
                            private val pending = AtomicBoolean(false)
                            private val revoked = AtomicBoolean(false)

                            override fun persistPendingAuthenticatedRevocation(pairingIdentifier: String, reason: String) {
                                pending.set(true)
                            }

                            override fun persistAuthenticatedRevocation(pairingIdentifier: String, reason: String) {
                                check(pending.get()) { "Durable pending revocation is required" }
                                revoked.set(true)
                                pending.set(false)
                            }

                            override fun isAdmissionBlocked(pairingIdentifier: String): Boolean = pending.get() || revoked.get()
                        },
                    revocationCoordinator = revocationCoordinator,
                )
            } catch (failure: Throwable) {
                if (cleanupInteropPairing(storedFactory, revocationCoordinator, pairingId) != null) {
                    failure.addSuppressed(AssertionError("Interop pairing cleanup was incomplete"))
                }
                transcriptContext.fill(0)
                boundContext.fill(0)
                throw failure
            }
        sessionReference.set(session)
        try {
            session.start()
            await(routeSelected, "selected route")
            await(active, "Protocol v1 active session")
            await(configured, "VideoConfig")
            await(keyframe, "keyframe")
            await(delta, "delta frame")
            await(touchSent, "touch send")
            assertEquals(expectedRoute, selectedRoute.get())
            assertTrue("Product session failed: ${synchronized(failures) { failures.map { it.message } }}", failures.isEmpty())
            println(
                "PHASE3_ANDROID_INTEROP_DEVICE_PASS route=${expectedRoute.name.lowercase()} epoch=$epoch " +
                    "kdf_kat=true transcript_kat=true video_config=true keyframe=true delta=true touch=true " +
                    "protocol_v1=true application_e2ee=true lifecycle_store=test_isolated",
            )
        } finally {
            val closeFailure = runCatching(session::close).exceptionOrNull()
            val pairingCleanupFailure = cleanupInteropPairing(storedFactory, revocationCoordinator, pairingId)
            val fileCleanupFailed = !secretFile.delete() && secretFile.exists()
            transcriptContext.fill(0)
            boundContext.fill(0)
            if (closeFailure != null) {
                if (pairingCleanupFailure != null) closeFailure.addSuppressed(AssertionError("Interop pairing cleanup was incomplete"))
                if (fileCleanupFailed) closeFailure.addSuppressed(AssertionError("Interop private-file cleanup was incomplete"))
                throw closeFailure
            }
            if (pairingCleanupFailure != null) throw AssertionError("Interop pairing cleanup was incomplete")
            if (fileCleanupFailed) throw AssertionError("Interop private-file cleanup was incomplete")
        }
    }

    private fun cleanupInteropPairing(
        storedFactory: AndroidStoredInternetSessionFactory,
        revocationCoordinator: InternetProductRevocationCoordinator,
        pairingId: String,
    ): Throwable? {
        val failures = mutableListOf<Throwable>()
        runCatching {
            revocationCoordinator.withCredentialMutationAdmission(durableBlock = { false }) {
                storedFactory.retryPendingPairingPersistenceCleanup(currentPairingIdentifier = pairingId)
            }
        }.onFailure(failures::add)
        runCatching { storedFactory.removePairingSecrets(pairingId) }.onFailure(failures::add)
        return failures.firstOrNull()
    }

    private fun await(latch: CountDownLatch, gate: String) {
        assertTrue("Timed out waiting for $gate", latch.await(TIMEOUT_SECONDS, TimeUnit.SECONDS))
    }

    private class Arguments(private val values: android.os.Bundle) {
        fun required(name: String): String =
            values.getString(name)?.takeIf(String::isNotBlank) ?: error("Missing instrumentation argument: $name")

        fun boolean(name: String): Boolean =
            required(name).let { value ->
                require(value == "true" || value == "false") { "$name must be true or false" }
                value.toBoolean()
            }

        fun privateConfigFile(context: Context): File {
            val name = required("configFile")
            require(name.matches(Regex("[a-zA-Z0-9._-]{1,128}"))) { "configFile must be a private basename" }
            val root = context.filesDir.canonicalFile
            val file = File(root, name).canonicalFile
            require(file.parentFile == root && file.isFile) { "Private interop configuration is unavailable" }
            val permissions = android.system.Os.stat(file.path).st_mode and 0x1ff
            require(permissions == 0x180) { "Private interop configuration must use mode 0600" }
            return file
        }
    }

    private data class SecretConfiguration(
        val signalingUrl: String,
        val sessionId: String,
        val deviceToken: String,
        val sessionEpoch: Long,
        val hostId: String,
        val deviceId: String,
        val sharedSecret: ByteArray,
        val bootstrapSecret: ByteArray,
        val transcriptContext: ByteArray,
        val expectedBoundContextHex: String,
        val expectedTrafficKeyId: String,
        val iceUrls: List<String>,
        val iceUsername: String?,
        val iceCredential: String?,
        val allowInsecureSignaling: Boolean,
    ) {
        companion object {
            private const val MAX_CONFIG_BYTES = 16 * 1024
            private val REQUIRED_KEYS =
                setOf(
                    "signaling_url", "session_id", "device_token", "session_epoch", "host_id", "device_id",
                    "shared_secret_base64", "bootstrap_secret_base64", "transcript_context_base64",
                    "expected_bound_context_hex", "expected_traffic_key_id", "ice_urls",
                    "ice_username", "ice_credential", "allow_insecure_signaling",
                )

            fun readAndDelete(file: File): SecretConfiguration {
                val encoded = file.readBytes()
                try {
                    require(encoded.size in 2..MAX_CONFIG_BYTES) { "Private interop configuration size is invalid" }
                    check(file.delete() || !file.exists()) { "Private interop configuration could not be deleted after reading" }
                    val root = JsonParser.parseString(encoded.toString(Charsets.UTF_8)).asJsonObject
                    require(root.keySet() == REQUIRED_KEYS) { "Private interop configuration fields are invalid" }
                    return decode(root)
                } finally {
                    encoded.fill(0)
                    file.delete()
                }
            }

            private fun decode(root: JsonObject): SecretConfiguration =
                SecretConfiguration(
                    signalingUrl = root.requiredString("signaling_url"),
                    sessionId = root.requiredString("session_id"),
                    deviceToken = root.requiredString("device_token"),
                    sessionEpoch = root.requiredPositiveLong("session_epoch"),
                    hostId = root.requiredString("host_id"),
                    deviceId = root.requiredString("device_id"),
                    sharedSecret = root.requiredBase64("shared_secret_base64"),
                    bootstrapSecret = root.requiredBase64("bootstrap_secret_base64", 32),
                    transcriptContext = root.requiredBase64("transcript_context_base64", 32),
                    expectedBoundContextHex = root.requiredHex("expected_bound_context_hex", 32),
                    expectedTrafficKeyId = root.requiredHex("expected_traffic_key_id", 32),
                    iceUrls = root.getAsJsonArray("ice_urls").map { it.asString }.also { require(it.isNotEmpty()) },
                    iceUsername = root.optionalString("ice_username"),
                    iceCredential = root.optionalString("ice_credential"),
                    allowInsecureSignaling = root.get("allow_insecure_signaling").asBoolean,
                )

            private fun JsonObject.requiredString(name: String): String =
                get(name)?.takeIf { it.isJsonPrimitive && it.asJsonPrimitive.isString }?.asString
                    ?.takeIf { it.isNotBlank() && it.length <= 4096 } ?: error("$name is invalid")

            private fun JsonObject.optionalString(name: String): String? =
                get(name)?.takeUnless { it.isJsonNull }?.let {
                    require(it.isJsonPrimitive && it.asJsonPrimitive.isString) { "$name is invalid" }
                    it.asString.takeIf(String::isNotBlank)
                }

            private fun JsonObject.requiredPositiveLong(name: String): Long =
                get(name)?.takeIf { it.isJsonPrimitive && it.asJsonPrimitive.isNumber }?.asLong
                    ?.also { require(it > 0) } ?: error("$name is invalid")

            private fun JsonObject.requiredBase64(name: String, expectedBytes: Int? = null): ByteArray =
                Base64.getDecoder().decode(requiredString(name)).also {
                    require(it.isNotEmpty() && (expectedBytes == null || it.size == expectedBytes)) { "$name is invalid" }
                }

            private fun JsonObject.requiredHex(name: String, bytes: Int): String =
                requiredString(name).lowercase().also {
                    require(it.length == bytes * 2 && it.all { character -> character in "0123456789abcdef" }) { "$name is invalid" }
                }
        }
    }

    companion object {
        private val KEYFRAME = "VIBE-ANDROID-INTEROP-KEYFRAME".toByteArray()
        private val DELTA = "VIBE-ANDROID-INTEROP-DELTA".toByteArray()
        private const val TIMEOUT_SECONDS = 60L
    }
}

private class InteropSecurityStateStore : SecurityStateStore {
    private var state = DurableSecurityState()

    @Synchronized
    override fun load(): DurableSecurityState = state.copy()

    @Synchronized
    override fun persist(state: DurableSecurityState) {
        this.state = state.copy()
    }
}

private fun ByteArray.hex(): String = joinToString("") { "%02x".format(it) }
