# Nubia P0110 PR272 Android UI/UX E2E

This record covers the PR #272 Android display-selection UI confirmation path and a focused UI/UX walk-through on the connected Android device. The run held `/tmp/vibe-screen-device-android.lock` for this task and used explicit `adb -s <redacted-adb-serial>` targeting for every device command.

## Device

- Device identity: nubia P0110 / pacific / Android 16 / SDK 36
- Serial: <redacted-adb-serial>
- Physical size: 1264x2800
- Physical density: 560

Identity was rechecked before the final evidence update with:

```text
manufacturer=nubia
model=P0110
device=pacific
release=16
sdk=36
Physical size: 1264x2800
Physical density: 560
```

## Commands And Artifacts

- Build and install: `gradle-build.txt`, `adb-install.txt`
- App launch and reverse state: `adb-start-portrait.txt`, `adb-reverse-list.txt`
- Screenshots: `portrait-initial.png`, `portrait-streaming-after-rotate.png`, `controlbar-revealed-retry.png`, `display-dropdown-retry-open.png`, `settings-after-tap.png`, `disconnected-after-control-disconnect.png`
- UIAutomator dumps: `window-portrait-initial.xml`, `window-portrait-streaming.xml`, `window-controlbar-revealed-retry.xml`, `window-display-dropdown-retry-open.xml`, `window-settings.xml`, `window-disconnected-after.xml`
- Display-selection logs: `real-host-display-selection-events-v3.txt`, `diag-display-selection-v3-events.txt`, `real-host-display-selection-instrumentation-v3.txt`
- Repeat-attempt diagnostics: `real-host-display-selection-instrumentation-v4.txt`, `real-host-display-selection-instrumentation-v5.txt`, `diag-display-selection-v4-events.txt`, `diag-after-v5.log`

Midscene was not used for this pass because the local model environment was not configured for a synchronous screenshot/analyze/act loop. The reproducible evidence is therefore raw ADB screenshots, UIAutomator XML, app diagnostics, Gradle output, and instrumentation logs.

## Observed UI/UX States

### Streaming Surface And Control Capsule

`portrait-streaming-after-rotate.png` and `window-portrait-streaming.xml` show the stream surface after rotation with `videoViewport` bounds `[427,0][2373,1264]` and the reveal target `inputViewport` exposed with `content-desc="Show stream controls"`.
The UIAutomator hierarchy records `rotation="1"`, so this is the landscape, 600dp-plus-width surface on the Nubia phone: 2800 px at 560 dpi is 800 dp wide, while the short side remains about 361 dp. `portrait-initial.png` records the app launch orientation, but this run does not claim a complete portrait streaming acceptance pass.

`controlbar-revealed-retry.png` and `window-controlbar-revealed-retry.xml` show the compact centered control bar over the real stream. UIAutomator reported these interactive regions:

```text
connectionSecurityGroup [875,231][1158,399] content-desc="USB connection, ADB reverse"
displayCapsuleGroup    [1179,231][1463,399] content-desc="Choose display, currently Built-in Retina Display"
controlHostActionsButton [1477,231][1645,399] content-desc="Window actions"
controlSettingsButton    [1673,231][1841,399] content-desc="Settings"
controlDisconnectButton  [1897,231][2065,399] content-desc="Disconnect"
```

Those bounds are all larger than the 48 dp minimum hit target on this 560 dpi device.

### Display Dropdown

`display-dropdown-retry-open.png` and `window-display-dropdown-retry-open.xml` show the display capsule opened from the control bar while the active label remained `Built-in Retina Display`. The connected Host published three selectable displays to the client diagnostics:

```text
1:Built-in Retina Display:1512x982:primary=true
2:DELL U2723QE:1920x1080:primary=false
telemachus-virtual-extended:Vibe Screen Virtual (extended):2000x1200:primary=false
```

The visual dropdown screenshot preserves the pre-selection active state. The runtime selection confirmation was then verified through the instrumented real-Host path below.

### Settings Dialog

`settings-after-tap.png` and `window-settings.xml` show the settings dialog opened from the control bar. The dump includes:

```text
Display settings
Show Stats
FPS, bitrate, resolution
Sustained use
No device warnings
```

The `showStatsSwitch` bounds were `[2310,621][2478,789]`, again larger than the minimum touch target. Later screenshots in this directory (`settings-control-contrast.png`, `settings-motionevent-contrast.png`, `settings-natural-rotation-mapped.png`, `settings-rotated-coord-contrast.png`) capture repeated settings-dialog visibility while retrying the tap mapping.

### Disconnect Confirmation

`disconnected-after-control-disconnect.png` and `window-disconnected-after.xml` show the confirmation dialog after invoking disconnect from the control bar:

```text
Disconnect?
This ends the current screen session with the Mac.
CANCEL
DISCONNECT
```

This verifies the confirmation surface and action labels. The final post-confirmation disconnected screen was not completed in this run, so this record does not close disconnect-state acceptance beyond the confirmation dialog.

## PR #272 Display-Selection Confirmation Result

The strongest evidence for PR #272 is the real-Host display-selection event order from `diag-display-selection-v3-events.txt` and the observed state file `real-host-display-selection-events-v3.txt`. The opt-in temporary instrumentation selected display `2` from the capsule popup, and the app diagnostics recorded:

```text
3139:[1787388759503] MA: capsule selectDisplay target=2 from=1
3147:[1787388759647] MA: Decoder configuration committed 1920x1080 epoch=2
3148:[1787388759651] MA: onDisplaysAvailable: count=3 selected=2 ...
3150:[1787388759653] MA: onDisplayGeometry: 1920x1080 @ 0 deg
```

The test-side snapshot file confirms the UI-visible selected label changed only after the real Host published selected display `2`:

```text
initial: selected=1 label=Built-in Retina Display selectorVisible=true selectorEnabled=true displays=1:Built-in Retina Display:1512x982:primary=true:virtual=false, 2:DELL U2723QE:1920x1080:primary=false:virtual=false, telemachus-virtual-extended:Vibe Screen Virtual (extended):2000x1200:primary=false:virtual=true
after menu item click: selected=2 label=DELL U2723QE selectorVisible=true selectorEnabled=true displays=1:Built-in Retina Display:1512x982:primary=true:virtual=false, 2:DELL U2723QE:1920x1080:primary=false:virtual=false, telemachus-virtual-extended:Vibe Screen Virtual (extended):2000x1200:primary=false:virtual=true
```

`real-host-display-selection-instrumentation-v3.txt` ended with an over-strict assertion failure because the Host confirmation arrived before the test could observe an intermediate non-confirmed label state. The failure happened after the popup selection and after the confirmed selected-display update above, so it is retained as raw path evidence rather than reported as a passing automated test.

The temporary opt-in instrumentation source used for this real-Host probe was removed before the final diff. The retained files are evidence only.

## Repeat Attempts And Boundaries

Follow-up attempts v4/v5 were polluted by external state: the device showed a package-open permission controller prompt for the test package, and later diagnostics showed repeated retryable `TRANSPORT_CLOSED` session endings after the Host/listener state degraded. These retries are not treated as product failures, and they are not used to contradict the successful v3 display-selection path evidence.

This run verifies the narrow PR #272 display-selection confirmation behavior on nubia P0110 / pacific / Android 16 / SDK 36. It also provides visual evidence for the control capsule, display dropdown, settings dialog, stream rotation surface, and disconnect confirmation dialog. It does not claim:

- Any README acceptance gate closure.
- Full final disconnected-state completion after pressing the confirm button.
- Full TalkBack traversal coverage.
- Full small-tablet product acceptance, or full portrait plus landscape matrix acceptance.
- Latency, soak, native-pointer, stylus, controller, LAN, or iOS acceptance.

## Readiness Conclusion

For the narrow PR #272 display-selection UI confirmation fix, this evidence supports moving the PR out of draft after queued CI jobs complete successfully and reviewers accept the scoped evidence boundary. Broader Android UI/UX readiness remains fail-closed to the open items listed above.
