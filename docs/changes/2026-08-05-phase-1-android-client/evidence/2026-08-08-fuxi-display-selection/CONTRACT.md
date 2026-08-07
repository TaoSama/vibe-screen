# Display Selection End-to-End — Implementation Contract (internal working notes)

Scope: Add README target "top display-selection capsule + multi-display end-to-end
selection" plus 3 UX fixes. Backward compatible with legacy session and existing tests.

## Wire capability
- Use existing CAPABILITY_MULTI_DISPLAY (=18) as the display-selection wire capability.
  DO NOT add/renumber proto fields.
- Client advertises MULTI_DISPLAY in ClientHello.capabilities (in addition to TOUCH).
- Host adds MULTI_DISPLAY to hostCapabilities (production path).
- negotiated = advertised ∩ host. Client maps ClientSessionCapabilities.displaySelection =
  (MULTI_DISPLAY ∈ negotiated). Android onSessionAccepted invariant
  (negotiated == advertised ∩ host) stays satisfied because both sides now include it.

## HOST (Swift) — baseline/MacHost
Session is AppKit-free; it must NOT call DisplayCatalog directly. Feed it a display list.

1. ProtocolV1SessionConfiguration:
   - add: var displays: [ProtocolV1DisplayInfo]  (id:String, name:String, width:Int,
     height:Int, isPrimary:Bool, isVirtual:Bool). Keep existing displayID/displayName/
     displayIsVirtual as the "currently captured" identity (source of the primary/active
     descriptor). If displays empty, synthesize one from the existing fields (keeps
     single-display self-test: count==1).
   - productionHostCapabilities(touchEnabled:): also include .multiDisplay.
2. ListDisplaysRequest -> return ALL configured displays (map each ProtocolV1DisplayInfo to
   VSDisplayDescriptor; isPrimary flag from info; scaleFactor=1). Active display's descriptor
   must equal displayDescriptor() so client's expectedDisplayId matching still holds.
3. StartDisplayRequest.sourceDisplayID:
   - empty OR == current configuration.displayID -> start current (existing behavior).
   - matches another configured display id -> ACCEPT, emit new Action .selectDisplay(id:String)
     so StreamingServer/AppDelegate switch capture; respond with that display's descriptor.
   - unknown/offline id -> safe fallback: either reject with VSProtocolError(invalidState) OR
     fall back to primary and report truthfully. Choose reject-with-error for pre-stream, and
     for runtime switch fall back to current + DisplayChanged unchanged. Keep it simple:
     reject unknown id with invalidState error (never crash).
4. Runtime switch while STREAMING: add coordinator API to re-run StartDisplay selection:
   new configEpoch (increment), new streamID may stay 1 (single stream) — MUST send a new
   VideoConfig with configEpoch>previous so client re-negotiates; then DisplayChanged for the
   selected descriptor after VideoConfigResult (reuse existing awaitingVideoConfig->streaming).
   Simplest: expose selectDisplayFromClient() that transitions streaming->awaitingVideoConfig
   with incremented configEpoch and sends StartDisplayResponse+VideoConfig, mirroring startDisplay().
5. StreamingServer: surface .selectDisplay action via a new callback
   onDisplaySelectionRequested?((String)->Void) invoked on network queue -> hop to MainActor.
   Add setProtocolV1Displays([...]) alongside setProtocolV1VideoConfiguration so the session
   gets the full catalog at session creation.
6. AppDelegate:
   - When configuring video (setProtocolV1VideoConfiguration site ~1854), also compute the
     display catalog from DisplayCatalog.onlineDisplays() and pass via setProtocolV1Displays,
     mapping CGDirectDisplayID -> String(id). The active/captured display id is
     String(captureDisplayID) (already used).
   - Implement onDisplaySelectionRequested: parse String -> CGDirectDisplayID (UInt32); if it
     resolves via DisplayCatalog.resolve to a real online display, set
     settings.selectedDisplayID = resolvedID, settings.selectedDisplayUUID(persistentUUID),
     settings.displaySource = .selectedDisplay on MainActor. That drives the existing
     reconfiguration path (recapture) and re-publishes video config. The coordinator's
     selectDisplayFromClient() drives the protocol re-negotiation.
   - IMPORTANT ordering: protocol re-negotiation (new VideoConfig) must reflect the NEW
     captured display geometry. Reuse existing updateDisplaySize/makeDisplayChanged flow that
     already fires after reconfiguration. Keep single-client/single-stream + security checks.
7. Self-tests to update (must stay green):
   - ProtocolV1SelfTest: makeSession() has 1 display -> ListDisplays count==1 still true;
     negotiatedCapabilities now == [.touch, .multiDisplay] (sorted by rawValue: touch=3,
     multiDisplay=18) — update the equality asserts to include .multiDisplay, and hostHello
     .capabilities accordingly. Add a NEW case: configure 2 displays, assert ListDisplays
     returns 2 with correct ids/isPrimary; StartDisplay(second id) accepted + emits selectDisplay
     action + descriptor is the second; unknown id -> invalidState error.
   - HostSelfTest: unaffected (still uses DisplayCatalog directly).
   - Run: swift build -c release; .build/release/Telemachus --protocol-v1-self-test;
     --transport-self-test; --host-self-test. Paste outputs.

## ANDROID (Kotlin) — baseline/AndroidClient
1. ProtocolV1Session.kt:
   - advertisedCapabilities = setOf(TOUCH, MULTI_DISPLAY).
   - Keep onSessionAccepted invariant; expose negotiatedCapabilities via a public accessor
     (e.g. val negotiated: Set<Capability>) so StreamClient can build ClientSessionCapabilities.
   - Store full display list from LIST_DISPLAYS_RESPONSE. Keep auto-start of the PRIMARY (or
     first) display so existing tests pass: onDisplays picks primary (isPrimary) else first,
     sends StartDisplay(source_display_id) as today. ALSO emit a new
     Action.DisplaysAvailable(displays: List<DisplayOption>, selectedId: String) BEFORE the Send,
     where DisplayOption(id,name,width,height,isPrimary). Existing tests call .single() on the
     result of receive(displayList) expecting the Send — CHANGE: those tests will need the new
     action. To avoid breaking ProtocolV1SessionTest .single() expectation, prefer: keep receive()
     returning the Send only, and expose displays + selectedDisplayId via public getters +
     a separate Action for the UI. SAFEST: return listOf(DisplaysAvailable, Send) and UPDATE the
     two tests (ProtocolV1SessionTest line ~55, StreamClientProtocolV1IntegrationTest) to index
     the Send instead of .single(). Update tests accordingly.
   - Add public fun selectDisplay(displayId): Envelope? — only valid when STREAMING and id is a
     known, non-current display; transitions to a REDISPLAY_REQUESTED state and returns
     StartDisplayRequest(mode=EXISTING, source_display_id=displayId). onStartDisplay must accept
     REDISPLAY_REQUESTED too. onVideoConfig already accepts STREAMING w/ configEpoch>current — but
     state is REDISPLAY_REQUESTED now; allow REDISPLAY_REQUESTED in onVideoConfig. On accept, set
     displayId to selected; publish DisplayGeometryChanged (reset displayGeometryPublished=false so
     geometry re-publishes for the new display).
2. StreamClient.kt:
   - Handle Action.DisplaysAvailable -> new callback onDisplaysAvailable?((List<StreamDisplayOption>,
     selectedId)->Unit). Define StreamDisplayOption data class in ClientExperience.kt or StreamClient.
   - Add fun selectDisplay(displayId): submit outbound ProtocolBatch that calls session.selectDisplay.
   - Build ClientSessionBinding capabilities from session.negotiated (displaySelection = MULTI_DISPLAY).
     Find where binding/capabilities are derived (MainActivity.currentSessionBinding uses
     client.sessionBinding()? ). Provide a way for MainActivity to read negotiated caps + display list.
3. MainActivity.kt + activity_main.xml + strings.xml:
   (a) UX FIX mode toggle truncation: the 3 MaterialButtons (modeUSB/modeWireless/modeInternet)
       truncate "Trusted LAN"/"Internet". Fix: set android:maxLines="1", app:autoSizeTextType="uniform"
       with sensible min/max (e.g. 10sp..14sp), and android:insetTop/Bottom=0 / reduce horizontal
       padding so text fits. Keep weights equal. Verify on device screenshot (waiting state).
   (b) UX FIX connected control layer: add a top control layer (CardView/LinearLayout) shown in
       connected state, tap-to-reveal + auto-fade (e.g. 3s). Contains: display-selection capsule
       (a MaterialButtonToggleGroup or horizontal chips built at runtime from display list),
       Disconnect icon-button, Settings icon-button. All icon buttons get contentDescription +
       tooltipText (use existing lucide-like drawables: ic_settings exists; add simple vector for
       disconnect/displays or reuse android system icons). Stats floatbar + settings FAB should hide
       behind this layer or move into it; do NOT permanently occlude video. Tap on video toggles
       the control layer; it auto-hides after timeout. Ensure text fits, no card-in-card nesting for
       page sections (the control bar itself is a single toolbar card = OK).
   (c) UX FIX reconnecting vs waiting: during automatic retry (USB automaticUsbConnect /
       wireless auto-reconnect), connectionTitle should read "Reconnecting…" not "Waiting for your
       Mac". Add string reconnecting_short = "Reconnecting…". Track a boolean (isReconnecting) set when
       a retry is scheduled/in-flight and cleared on connect/idle; updateDisconnectedHeader uses it.
   - Display capsule behavior: enabled only when currentSessionBinding().capabilities.displaySelection
     is true (negotiated). Single-display: show the one current display selected/disabled (still
     correctly labeled). Selecting a different entry calls streamClient.selectDisplay(id).
   - Wire onDisplaysAvailable to populate the capsule; wire DisplayChanged/new video config through
     existing displayLifecycle (do NOT break surface lifecycle).
4. Tests: update ProtocolV1SessionTest + StreamClientProtocolV1IntegrationTest for new action
   ordering + MULTI_DISPLAY negotiated set + selectDisplay path. Keep them green (JVM unit tests):
   cd baseline/AndroidClient && ANDROID_HOME=/Users/luwentao/Library/Android/sdk TELEMACHUS_VERSION=0.0.0 \
     ./gradlew --no-daemon :app:testDebugUnitTest --tests '*ProtocolV1SessionTest' \
     --tests '*StreamClientProtocolV1IntegrationTest'

## Build/verify (device 8a023e3a, USB, keep stream alive)
- Host: cd baseline/MacHost && swift build -c release; run self-tests.
- Android debug: cd baseline/AndroidClient && ANDROID_HOME=/Users/luwentao/Library/Android/sdk \
  TELEMACHUS_VERSION=0.0.0 ./gradlew --no-daemon :app:assembleDebug
- Install: adb -s 8a023e3a install -r -g <apk>
- Evidence dir: docs/changes/2026-08-05-phase-1-android-client/evidence/2026-08-08-fuxi-display-selection/
- Connected screen has FLAG_SECURE -> screencap black; use logcat VD Decode stats
  (dropped=0, counts increasing, no decoder_surface_timeout) + Host log as authority.
  Waiting/disconnected chrome may be screenshotted (before/after for the 3 UX fixes + capsule).
- Prove: logcat shows ListDisplays sent + >=1 display received; StartDisplay(source_display_id)
  reaches host (host log); stream not regressed after selection.

## Constraints
- No proto field renumber; no README/tools changes; no push/PR. Device -s 8a023e3a only.
- Files <=500 lines where reasonable; handle all errors; icon buttons need contentDescription+tooltip.
- Don't revert pre-existing user edits (videoViewport visible; MainActivity waiting-surface comment).

