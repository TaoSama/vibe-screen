package dev.telemachus.display

import java.io.File
import org.junit.Assert.assertTrue
import org.junit.Test

class MainActivityControllerForwardingContractTest {
    @Test
    fun foregroundReturnRequestsFreshFrameForEveryActiveSessionType() {
        val source = mainActivitySource()
        val onStart = extractMethod(source, "override fun onStart")

        assertContains(onStart, "isInForeground = true")
        assertContains(onStart, "setStreamingWindowState(true)")
        assertContains(onStart, "streamClient?.requestKeyframe(force = true, reason = FOREGROUND_KEYFRAME_REASON)")
        assertContains(onStart, "internetSession?.requestKeyframe(FOREGROUND_KEYFRAME_REASON)")
        assertBefore(onStart, "setStreamingWindowState(true)", "streamClient?.requestKeyframe(force = true")
        assertBefore(onStart, "streamClient?.requestKeyframe(force = true", "internetSession?.requestKeyframe")
    }

    @Test
    fun backgroundLifecycleCancelsInputAndPausesRetryBeforeStopping() {
        val source = mainActivitySource()
        val onStop = extractMethod(source, "override fun onStop")

        assertContains(onStop, "completeCurrentNativeInputBoundary(InputPhase.INPUT_PHASE_CANCELLED)")
        assertContains(onStop, "isInForeground = false")
        assertContains(onStop, "applyStreamingWindowState(connected = isConnected, foreground = false)")
        assertContains(onStop, "autoConnectHandler.removeCallbacks(autoConnectRunnable)")
        assertContains(onStop, "wirelessReconnectHandler.removeCallbacks(wirelessReconnectRunnable)")
        assertBefore(onStop, "completeCurrentNativeInputBoundary(InputPhase.INPUT_PHASE_CANCELLED)", "isInForeground = false")
        assertBefore(onStop, "applyStreamingWindowState(connected = isConnected, foreground = false)", "super.onStop()")
    }

    @Test
    fun controllerKeyEventsEnterProductionDispatchBeforeKeyboardFallback() {
        val source = mainActivitySource()
        val dispatchKeyEvent = extractMethod(source, "override fun dispatchKeyEvent")

        assertContains(dispatchKeyEvent, "if (!isInForeground || event.isSystemKey()) return super.dispatchKeyEvent(event)")
        assertContains(dispatchKeyEvent, "ControllerInputMapper.keyChange(event)?.let { change ->")
        assertContains(dispatchKeyEvent, "val active = isConnected || prefs.connectionMode == ConnectionMode.INTERNET && internetSession != null")
        assertContains(dispatchKeyEvent, "activeControllerSessionState()")
        assertContains(dispatchKeyEvent, "state.applyKey(change)")
        assertContains(dispatchKeyEvent, "sendStreamControllerDispatch(dispatch,")
        assertContains(dispatchKeyEvent, "controller key")
        assertBefore(dispatchKeyEvent, "if (!isInForeground", "ControllerInputMapper.keyChange(event)")
        assertContains(dispatchKeyEvent, "if (!isConnected || event.isSystemKey()) return super.dispatchKeyEvent(event)")
        assertContains(dispatchKeyEvent, "ControllerInputConsumptionPolicy.shouldConsume(active, isSystemKey = false)")
        assertBefore(dispatchKeyEvent, "ControllerInputMapper.keyChange(event)", "AndroidKeyInputMapper.map(")
    }

    @Test
    fun controllerMotionEventsEnterProductionDispatchBeforeStylusAndPointerFallbacks() {
        val source = mainActivitySource()
        val genericMotion = extractMethod(source, "private fun handleGenericMotion")

        assertContains(source, "binding.inputViewport.setOnGenericMotionListener { view, event ->")
        assertContains(source, "handleGenericMotion(view, event)")
        assertContains(genericMotion, "if (!isInForeground) return false")
        assertContains(genericMotion, "if (!isConnected) return false")
        assertContains(genericMotion, "ControllerInputMapper.snapshot(event)?.let { snapshot ->")
        assertContains(genericMotion, "streamControllerSessionState.applyMotion(snapshot)")
        assertContains(genericMotion, "sendStreamControllerDispatch(dispatch,")
        assertContains(genericMotion, "controller motion")
        assertContains(genericMotion, "ControllerInputConsumptionPolicy.shouldConsume(isConnected, isSystemKey = false)")
        assertBefore(genericMotion, "ControllerInputMapper.snapshot(event)", "StylusInputMapper.snapshot(event)")
        assertBefore(genericMotion, "ControllerInputMapper.snapshot(event)", "ClientPointerInput(")
    }

    @Test
    fun touchEventsAreDroppedBeforeAnyTransportDispatchWhenBackgrounded() {
        val source = mainActivitySource()
        val touchHandler = extractMethod(source, "private fun handleTouch")

        assertContains(touchHandler, "if (!isInForeground) return")
        assertBefore(touchHandler, "if (!isInForeground) return", "consumeHiddenControlRevealGesture(event)")
        assertBefore(touchHandler, "if (!isInForeground) return", "prefs.connectionMode == ConnectionMode.INTERNET")
        assertBefore(touchHandler, "if (!isInForeground) return", "streamClient?.sendMotionTouch(")
    }

    @Test
    fun controllerDispatchUsesNegotiatedSessionBindingAndStreamClientSink() {
        val source = mainActivitySource()
        val dispatch = extractMethod(source, "private fun sendStreamControllerDispatch")
        val internetDispatch = extractMethod(source, "private fun sendInternetControllerDispatch")
        val sink = extractClass(source, "private inner class StreamClientInputSink")

        assertContains(dispatch, "if (prefs.connectionMode == ConnectionMode.INTERNET)")
        assertContains(dispatch, "return sendInternetControllerDispatch(dispatch, source)")
        assertContains(dispatch, "ClientInputDispatch(currentSessionBinding()).sendController(ClientControllerInput(dispatch))")
        assertContains(dispatch, "ClientInputDispatchResult.SENT -> true")
        assertContains(dispatch, "ClientInputDispatchResult.REJECTED ->")
        assertContains(dispatch, "ClientInputDispatchResult.UNSUPPORTED ->")
        assertContains(internetDispatch, "ProductControllerEvent(internetInputIds.next(), sample)")
        assertContains(internetDispatch, "targetSession: InternetProductSession? = internetSession")
        assertContains(internetDispatch, "session.sendController(events, delivery)")
        assertContains(sink, "override fun sendController(input: ClientControllerInput): Boolean")
        assertContains(sink, "if (!isCurrentSession(client, generation)) return false")
        assertContains(sink, "return client.sendController(input.dispatch)")
    }

    @Test
    fun internetControllerUsesNegotiatedProductSessionAndResyncsOnVideoConfiguration() {
        val source = mainActivitySource()
        val genericMotion = extractMethod(source, "private fun handleGenericMotion")
        val internetConnect = extractMethod(source, "private fun connectInternet(")

        assertContains(genericMotion, "if (prefs.connectionMode == ConnectionMode.INTERNET)")
        assertContains(genericMotion, "ControllerInputMapper.snapshot(event)?.let { snapshot ->")
        assertContains(genericMotion, "internetControllerSessionState.applyMotion(snapshot)")
        assertContains(genericMotion, "ControllerInputConsumptionPolicy.shouldConsume(isConnected = true, isSystemKey = false)")
        assertBefore(genericMotion, "ControllerInputMapper.snapshot(event)", "handleInternetStylus(view, event, session")
        assertContains(internetConnect, "advertiseController = true")
        assertContains(internetConnect, "override fun onVideoConfigurationApplied(configuration: ProductVideoConfiguration)")
        assertContains(internetConnect, "internetControllerSessionState.resynchronize()")
        assertContains(internetConnect, "override fun onInputAck(")
        assertContains(internetConnect, "internetControllerSessionState.rejectConnection(controllerId, controllerEpoch)")
        assertContains(source, "sendInternetControllerDispatch(dispatch, \"internet controller video configuration\")")
        assertContains(source, "internetControllerSessionState.takeRelease()?.let { release ->")
        assertContains(source, "sendInternetControllerDispatch(release, \"internet controller release\", internet)")
        assertContains(source, "internet controller release")
    }

    @Test
    fun negotiatedControllerCapabilityPromotesSinkAndUsbLanClientsAdvertiseController() {
        val source = mainActivitySource()
        val displaysCallback = extractCallback(source, "callbackClient.onDisplaysAvailable = displays@")
        val usbConnect = extractMethod(source, "private fun connect(")
        val wirelessConnect = extractMethod(source, "private fun connectWireless(")
        val streamClient = streamClientSource()

        assertContains(displaysCallback, "dev.vibescreen.protocol.v1.Capability.CAPABILITY_CONTROLLER in negotiated")
        assertContains(displaysCallback, "controller = controller")
        assertContains(displaysCallback, "if (keyboard || nativePointer || controller)")
        assertContains(displaysCallback, "StreamClientInputSink(callbackClient, callbackGeneration)")
        assertContains(usbConnect, "StreamClient(host, port, applicationContext, advertiseController = true)")
        assertContains(wirelessConnect, "StreamClient(host, port, applicationContext, advertiseController = true)")
        assertContains(streamClient, "advertiseController = advertiseController")
    }

    @Test
    fun streamTeardownSendsControllerNeutralReleaseBeforeNativeInputRelease() {
        val source = mainActivitySource()
        val releaseBoundary = extractMethod(source, "private fun completeNativeInputBoundary")

        assertContains(releaseBoundary, "streamControllerSessionState.takeRelease()?.let { release ->")
        assertContains(releaseBoundary, "sendStreamControllerDispatch(release,")
        assertContains(releaseBoundary, "controller release")
        assertContains(releaseBoundary, "nativeInputReleaseCoordinator.completeBoundary(")
        assertBefore(releaseBoundary, "streamControllerSessionState.takeRelease()", "nativeInputReleaseCoordinator.completeBoundary(")
    }

    private fun assertContains(
        source: String,
        target: String,
    ) {
        assertTrue("Missing '$target'", source.contains(target))
    }

    private fun assertBefore(
        source: String,
        first: String,
        second: String,
    ) {
        val firstIndex = source.indexOf(first)
        val secondIndex = source.indexOf(second)
        assertTrue("Missing '$first'", firstIndex >= 0)
        assertTrue("Missing '$second'", secondIndex >= 0)
        assertTrue("Expected '$first' before '$second'", firstIndex < secondIndex)
    }

    private fun extractMethod(
        source: String,
        signature: String,
    ): String {
        val start = source.indexOf(signature)
        require(start >= 0) { "Method not found: $signature" }
        return extractBracedBlock(source, start, signature)
    }

    private fun extractClass(
        source: String,
        signature: String,
    ): String {
        val start = source.indexOf(signature)
        require(start >= 0) { "Class not found: $signature" }
        return extractBracedBlock(source, start, signature)
    }

    private fun extractCallback(
        source: String,
        startMarker: String,
    ): String {
        val start = source.indexOf(startMarker)
        require(start >= 0) { "Callback not found: $startMarker" }
        return extractBracedBlock(source, start, startMarker)
    }

    private fun extractBracedBlock(
        source: String,
        start: Int,
        label: String,
    ): String {
        var i = start
        var braceDepth = 0
        var inString = false
        var escaped = false
        var methodStarted = false
        while (i < source.length) {
            val current = source[i]
            when {
                inString -> {
                    if (escaped) {
                        escaped = false
                    } else if (current == '\\') {
                        escaped = true
                    } else if (current == '"') {
                        inString = false
                    }
                    i++
                }
                current == '"' -> {
                    inString = true
                    i++
                }
                current == '{' -> {
                    methodStarted = true
                    braceDepth++
                    i++
                }
                current == '}' -> {
                    braceDepth--
                    if (methodStarted && braceDepth == 0) return source.substring(start, i + 1)
                    i++
                }
                else -> i++
            }
        }
        error("Closing brace not found for $label")
    }

    private fun mainActivitySource(): String = source(MAIN_ACTIVITY_PATHS)

    private fun streamClientSource(): String = source(STREAM_CLIENT_PATHS)

    private fun source(paths: List<String>): String {
        var current = File(requireNotNull(System.getProperty("user.dir"))).canonicalFile
        repeat(8) {
            paths
                .map(current::resolve)
                .firstOrNull(File::isFile)
                ?.let { return it.readText() }
            current = current.parentFile?.canonicalFile ?: current
        }
        error(paths.first() + " not found from " + System.getProperty("user.dir"))
    }

    private companion object {
        val MAIN_ACTIVITY_PATHS =
            listOf(
                "app/src/main/java/dev/telemachus/display/MainActivity.kt",
                "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/MainActivity.kt",
            )

        val STREAM_CLIENT_PATHS =
            listOf(
                "app/src/main/java/dev/telemachus/display/StreamClient.kt",
                "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/StreamClient.kt",
            )
    }
}
