# 2026-09-10 Nubia P0110 no-Host connection primary actions large-text

Scope: Android connection-page Wireless and Internet primary action button large-text layout verification.

Device identity: Nubia P0110 / pacific / Android 16 / API 36, serial EP0110PZ0B9110152B verified online.

No-Host boundary: macOS Host was not started or modified; no Screen Recording, Accessibility, Microphone, or TCC operation was performed; no adb reverse mapping was created. adb reverse --list before and after tests was empty, and lsof -nP -iTCP:54321 -sTCP:LISTEN before and after returned status 1 with no listener output.

Results:

- PASS: git diff --check.
- PASS: ./gradlew --no-daemon :app:testDebugUnitTest --tests dev.telemachus.display.MainActivityTerminalGuidanceContractTest --rerun-tasks; retained XML reports 71 tests, 0 failures, 0 errors, including the new fontScale contract.
- PASS: ./gradlew --no-daemon :app:compileDebugAndroidTestKotlin.
- PASS: focused no-Host device instrumentation on P0110 - 16: ConnectionGuidanceLayoutInstrumentedTest#narrowPortraitLargeTextKeepsWirelessAndInternetPrimaryActionsSelfSizing and #primaryActionSelfSizingSurvivesNarrowWideRoundTripsAtLargeFontScales.
- PASS: make baseline-android-test. The first two attempts were interrupted by Gradle daemon stop events before a final result; logs are retained at logs/baseline-android-test-rerun.log and logs/baseline-android-test-final.log. The equivalent no-daemon Gradle task set passed afterward in logs/baseline-android-test-no-daemon-equivalent.log, followed by a successful original make target rerun retained at logs/baseline-android-test-second-final.log.
- BLOCKED/ENV: full ConnectionGuidanceLayoutInstrumentedTest class attempt aborted because the instrumentation process crashed during the pre-existing hiddenInternetSettingsDoesNotLeaveLeadingSecondaryActionGap test before the new tests ran. Raw Gradle log retained at logs/connection-guidance-layout-instrumented.log; focused coverage for this change passed afterward.

Coverage notes:

- Static contract verifies internetConnectButton, wirelessScanButton, wirelessReconnectButton, wirelessRescanButton, and wirelessOpenSettingsButton use the USB primary action self-sizing contract: wrap_content, minHeight=56dp, maxLines=2, singleLine=false, and ellipsize=none.
- Instrumented coverage verifies 320dp and 360dp portrait widths at fontScale 1.5 and 2.0 for all five target buttons: full text rendered, no ellipsis, no vertical clipping, height >= 56dp, no visible sibling overlap, and scroll reachability.
- Instrumented coverage verifies the same inflated layout survives narrow/wide round trips at both fontScale 1.5 and 2.0.
- Static contract verifies MainActivity does not handle fontScale in configChanges, so Android reinflates this XML on system font-size changes rather than needing a dynamic primary-button height applier.
