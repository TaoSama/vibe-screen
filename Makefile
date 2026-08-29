BUF_VERSION ?= v1.72.0
BUF := go run github.com/bufbuild/buf/cmd/buf@$(BUF_VERSION)
EVIDENCE_SERIAL ?=
EVIDENCE_DIR ?= .build/evidence
EVIDENCE_PACKAGE ?= dev.telemachus.display
EVIDENCE_PORT ?= 54321
MACOS_HOST_READINESS_PROBE_LOGIN_ITEM ?=
EVIDENCE_EXPECTED_MANUFACTURER ?=
EVIDENCE_EXPECTED_MODEL ?=
EVIDENCE_EXPECTED_DEVICE ?=
EVIDENCE_EXPECTED_ANDROID_RELEASE ?=
EVIDENCE_EXPECTED_SDK ?=
EVIDENCE_ALLOW_EXISTING_LOCKS ?=
EVIDENCE_HOST_PID ?= $(HOST_PID)
PHASE0_STABLE_RELEASE_MANIFEST ?= docs/changes/2026-08-22-phase0-stable-release-aggregate/phase0-stable-release-manifest.json
PHASE0_STABLE_RELEASE_SUMMARY ?= .build/evidence/phase0-stable-release/phase0-stable-release-summary.json
PHASE0_STABLE_RELEASE_REQUIRE_PASS ?=
PHASE0_STABLE_RELEASE_EXPECTED_SOURCE_COMMIT ?=
TRUSTED_LAN_HOST_PORT ?= 54321
TRUSTED_LAN_HOST_IPV4 ?=
TRUSTED_LAN_REQUIRE_HOST_LISTENER ?=
ACTIONABLE_ERROR_CURRENT_BASE_MANIFEST ?= $(EVIDENCE_DIR)/actionable-error-current-base.json
ACTIONABLE_ERROR_CURRENT_BASE_GATE_JSON ?= $(EVIDENCE_DIR)/actionable-error-current-base-gate.json
NATIVE_POINTER_HOST_LOG ?= $(HOME)/Library/Logs/Telemachus/telemachus.log
NATIVE_POINTER_OBSERVE_SECONDS ?= 20
NATIVE_POINTER_VISIBLE_RESULT_NOTE ?=
NATIVE_POINTER_HOST_READY_ARG ?=
STYLUS_HOST_LOG ?= $(HOME)/Library/Logs/Telemachus/telemachus.log
STYLUS_OBSERVE_SECONDS ?= 20
STYLUS_DRAWING_OBSERVATION ?=
STYLUS_OBSERVED_PHYSICAL_DRAWING_ARG ?=
STYLUS_HOST_READY_ARG ?=
ANDROID_AUDIO_PLAYBACK_JSON ?= $(EVIDENCE_DIR)/android-audio-playback-observations.json
ANDROID_AUDIO_PLAYBACK_GATE_JSON ?= $(EVIDENCE_DIR)/android-audio-playback-summary.json
ANDROID_AUDIO_READINESS_LOGCAT_LINES ?= 2000
ANDROID_AUDIO_READINESS_MAX_LOG_BYTES ?= 262144
HARMONY_AVCODEC_HDC_TARGET ?=
HARMONY_AVCODEC_HAP ?=
PHASE2_DEVICE_CLASS ?=
PHASE2_TABLET_SIZE_INCHES ?=
PHASE2_STAND_SETUP ?=
PHASE2_CHARGER ?=
PHASE2_CABLE_OR_DOCK ?=
PHASE2_AMBIENT_TEMPERATURE_CELSIUS ?=
PHASE2_TRANSPORT ?= usb
PHASE2_VIDEO_PREFERENCES ?=
PHASE2_HOST_IDENTITY ?=
PHASE2_HOST_BUILD ?=
PHASE2_HOST_PID ?=
PHASE2_HOST_TELEMETRY_JSONL ?=
PHASE2_HOST_LOG ?=
PHASE2_APK_PATH ?=
PHASE2_APK_SHA256 ?=
PHASE2_RECOVERY_SCENARIOS ?=
PHASE2_GATE_OWNERS ?=
PHASE2_THERMAL_LIMIT_STATUS ?= 2
PHASE2_BATTERY_TEMPERATURE_LIMIT_CELSIUS ?=
PHASE2_MAXIMUM_NET_BATTERY_DRAIN_PERCENT ?=
PHASE2_TABLET_GATE ?=
PHASE2_TABLET_MANIFEST ?=
PHASE2_HARDWARE_KEYBOARD ?=
PHASE2_DEVICE_MEMORY ?=
PHASE2_DEVICE_ENVIRONMENT ?=
PHASE2_SOAK_READINESS ?=
PHASE2_TABLET_UI ?=
PHASE2_RECOVERY ?=
PHASE2_LOGIN_HEADLESS ?=
IOS_ACCEPTANCE_JSON ?= $(EVIDENCE_DIR)/acceptance.json
IOS_ACCEPTANCE_GATE_JSON ?= $(dir $(IOS_ACCEPTANCE_JSON))ios-device-acceptance-gate.json
IOS_HDR_EDR_OBSERVATIONS_JSON ?= $(EVIDENCE_DIR)/ios-hdr-edr-observations.json
IOS_HDR_EDR_GATE_JSON ?= $(dir $(IOS_HDR_EDR_OBSERVATIONS_JSON))ios-hdr-edr-gate.json
IOS_APP_SIGNING_READINESS_JSON ?= $(EVIDENCE_DIR)/ios-app-signing-readiness.json
IOS_APP_SIGNING_READINESS_GATE_JSON ?= $(dir $(IOS_APP_SIGNING_READINESS_JSON))ios-app-signing-readiness-gate.json
IOS_NATIVE_INPUT_OBSERVATIONS_JSON ?= $(EVIDENCE_DIR)/ios-native-input-observations.json
IOS_NATIVE_INPUT_GATE_JSON ?= $(dir $(IOS_NATIVE_INPUT_OBSERVATIONS_JSON))ios-native-input-gate.json
PHASE5_MULTI_CLIENT_GATE_JSON ?= $(EVIDENCE_DIR)/phase5-multi-client-current-base-gate.json
CLIPBOARD_E2E_GATE_JSON ?= $(EVIDENCE_DIR)/clipboard-e2e-gate.json
CLIPBOARD_E2E_HOST_READINESS_JSON ?= $(EVIDENCE_DIR)/host-readiness.json
CLIPBOARD_E2E_USB_PREFLIGHT_JSON ?= $(EVIDENCE_DIR)/usb-smoke-preflight.json
CLIPBOARD_E2E_LAN_PREFLIGHT_JSON ?= $(EVIDENCE_DIR)/trusted-lan-preflight.json
CLIPBOARD_E2E_ANDROID_INSTRUMENTATION_LOG ?= $(EVIDENCE_DIR)/android-clipboard-instrumentation.txt
CLIPBOARD_E2E_PRODUCT_JSON ?= $(EVIDENCE_DIR)/product-e2e.json
CLIPBOARD_E2E_REQUIRE_PASS ?=
FILE_TRANSFER_ANDROID_SMOKE_GATE_JSON ?= $(EVIDENCE_DIR)/file-transfer-android-smoke-gate.json
FILE_TRANSFER_ANDROID_SMOKE_HOST_READINESS_JSON ?= $(EVIDENCE_DIR)/host-readiness.json
FILE_TRANSFER_ANDROID_SMOKE_USB_PREFLIGHT_JSON ?= $(EVIDENCE_DIR)/usb-smoke-preflight.json
FILE_TRANSFER_ANDROID_SMOKE_LAN_PREFLIGHT_JSON ?= $(EVIDENCE_DIR)/trusted-lan-preflight.json
FILE_TRANSFER_ANDROID_SMOKE_ANDROID_INSTRUMENTATION_LOG ?= $(EVIDENCE_DIR)/android-file-transfer-instrumentation.txt
FILE_TRANSFER_ANDROID_SMOKE_PRODUCT_JSON ?= $(EVIDENCE_DIR)/file-transfer-product-e2e.json
FILE_TRANSFER_ANDROID_SMOKE_REQUIRE_PASS ?=
HOST_PID ?=
PHASE2_SOAK_DURATION ?= 8h
PHASE2_SOAK_PREFLIGHT_DURATION ?= 2s
PHASE2_SOAK_INTERVAL ?= 30s
TOUCH_RERUN_EXPECTED_HOST_SHA256 ?=
TOUCH_RERUN_EXPECTED_ANDROID_MANUFACTURER ?=
TOUCH_RERUN_EXPECTED_ANDROID_MODEL ?=
TOUCH_RERUN_EXPECTED_ANDROID_DEVICE ?=
TOUCH_RERUN_EXPECTED_ANDROID_RELEASE ?=
TOUCH_RERUN_EXPECTED_ANDROID_SDK ?=
TOUCH_RERUN_REQUIRE_CURRENT_SOURCE ?= 1
TOUCH_RERUN_PREFLIGHT ?= $(EVIDENCE_DIR)/touch-rerun-preflight.json
TOUCH_RERUN_INSTRUMENTATION ?= $(EVIDENCE_DIR)/touch-gesture-instrumentation.txt
TOUCH_RERUN_HOST_LOG ?= $(EVIDENCE_DIR)/host-log-touch-gesture-window.log
TOUCH_RERUN_EVENT_TAP ?= $(EVIDENCE_DIR)/listen-only-event-tap.log
RECONNECT_TIMING_TARGET_DEVICE ?= Nubia P0110 / pacific / Android 16 / SDK 36 / $(EVIDENCE_SERIAL)
RECONNECT_TIMING_OBSERVATIONS_JSON ?= $(EVIDENCE_DIR)/reconnect-timing-observations.json
RECONNECT_TIMING_REQUIRE_DISRUPTIONS ?=
RECONNECT_TIMING_BLOCKER_ARGS ?= --blocker "Host/app prerequisites prevented a real Protocol v1 reconnect timing run"
RECONNECT_TIMING_ARTIFACT_ARGS ?=
RECONNECT_TIMING_NOTES_ARG ?=
LATENCY_PREFLIGHT_INPUT ?=
LATENCY_DEVICE_INFO ?=
LATENCY_REPOSITORY_REVISION ?=
LATENCY_GATE_PROFILE ?=
LATENCY_MANIFEST ?= $(EVIDENCE_DIR)/manifest.json
PHASE3_LOCAL_SYNTHETIC_E2E_DIR ?= .build/phase3-local-synthetic-product-e2e
PHASE3_LOCAL_SYNTHETIC_E2E_PUBLIC_DIR ?= $(PHASE3_LOCAL_SYNTHETIC_E2E_DIR)/public
PHASE3_LOCAL_SYNTHETIC_E2E_TIMEOUT_SECONDS ?= 90
PHASE3_TURNSERVER ?= $(shell command -v turnserver 2>/dev/null)
PHASE3_ANDROID_INTEROP_EVIDENCE ?=
PHASE3_ANDROID_INTEROP_GATE_PROFILE ?= real-capture
PHASE3_INTERNET_SOAK_DIR ?= $(EVIDENCE_DIR)
PHASE3_INTERNET_SOAK_MANIFEST_JSON ?= $(PHASE3_INTERNET_SOAK_DIR)/phase3-internet-soak-manifest.json
PHASE3_INTERNET_SOAK_MANIFEST ?= $(PHASE3_INTERNET_SOAK_MANIFEST_JSON)
PHASE3_INTERNET_SOAK_GATE_JSON ?= $(PHASE3_INTERNET_SOAK_DIR)/phase3-internet-soak-gate.json
PHASE3_INTERNET_TURN_URI ?=
PHASE3_INTERNET_TURN_URIS ?=
PHASE3_INTERNET_SIGNALING_ORIGIN ?=
PHASE3_INTERNET_RELAY_ORIGIN ?=
PHASE3_INTERNET_AUTHORITY_SOURCE_ID ?=
PHASE3_INTERNET_REMOTE_PEER ?=
PHASE3_INTERNET_TLS_CERTIFICATE_SHA256 ?=
PHASE3_INTERNET_TURN_SECRET_SOURCE ?=
PHASE3_INTERNET_DEPLOYMENT_READINESS ?=
PHASE3_INTERNET_PLANNED_HANDOFFS ?=
PHASE3_INTERNET_HOST_BUILD ?=
PHASE3_INTERNET_ANDROID_ARTIFACT_SHA256 ?=
PHASE3_INTERNET_DURATION_SECONDS ?= 7200
PHASE3_INTERNET_SAMPLE_INTERVAL_SECONDS ?= 30
PHASE3_INTERNET_NOTES ?=
PHASE3_INTERNET_REMOTE_TURN_REPORT ?= $(PHASE3_INTERNET_SOAK_DIR)/remote-turn-verifier.json
PHASE3_INTERNET_MEDIA_CONTINUITY_REPORT ?= $(PHASE3_INTERNET_SOAK_DIR)/media-continuity.json
PHASE3_INTERNET_NETWORK_HANDOFF_REPORT ?= $(PHASE3_INTERNET_SOAK_DIR)/network-handoff.json
PHASE3_INTERNET_HANDOFF_REPORT ?= $(PHASE3_INTERNET_NETWORK_HANDOFF_REPORT)
PHASE3_INTERNET_REVOCATION_REPORT ?= $(PHASE3_INTERNET_SOAK_DIR)/revocation-propagation.json
PHASE3_INTERNET_SOAK_REPORT ?= $(PHASE3_INTERNET_SOAK_DIR)/soak-exact-window-report.json
PHASE3_INTERNET_BLOCKED_REASON ?=
PHASE3_INTERNET_ALLOW_BLOCKED ?=
PHASE3_WEBRTC_E2E_SCHEMA := dev.vibescreen.phase3-webrtc-e2e/v1
PHASE3_COTURN_COMPATIBLE_VERSIONS := 4.15.0 4.16.0 4.17.0
HARMONY_HDC_TARGET ?=
HARMONY_HAP ?=
HARMONY_SHA256SUMS ?=
HARMONY_SIGNATURE_CERTIFICATE ?=
HARMONY_SIGNATURE_CERTIFICATE_SHA256 ?=
HARMONY_HAP_READINESS_FLAGS ?=
HARMONY_HOST_COMMIT ?=
HARMONY_HOST_BUILD_SHA256 ?=
HARMONY_READINESS_JSON ?= $(EVIDENCE_DIR)/harmony-readiness.json
HARMONY_DEVICE_GATES_JSON ?= $(EVIDENCE_DIR)/harmony-device-gates.json
HARMONY_CURRENT_BASE_GATE_JSON ?= $(EVIDENCE_DIR)/harmony-current-base-gate.json
HARMONY_HAP_READINESS_DIR ?= $(EVIDENCE_DIR)
HARMONY_HAP_READINESS_JSON ?= $(HARMONY_HAP_READINESS_DIR)/harmony-hap-readiness.json
HARMONY_HOST_INTEROP_JSON ?= $(EVIDENCE_DIR)/harmony-host-interop.json
HARMONY_HOST_INTEROP_RUN_ID ?= harmony-host-interop-preflight
PHASE3_HOST_LOG ?=
PHASE3_ANDROID_LOG ?=
PHASE3_DEVICE_INFO ?=
PHASE3_NETWORK_PATH ?= unknown
PHASE3_HOST_SIGNING ?= unknown
PHASE3_SCREEN_RECORDING ?= unknown
PHASE3_MINIMUM_OUTPUT_FRAMES ?= 120
PHASE3_MAXIMUM_DROPPED_FRAMES ?= 0
WAKE_HOST_CURRENT_BASE_JSON ?= $(EVIDENCE_DIR)/wake-host-current-base-observations.json
WAKE_HOST_CURRENT_BASE_GATE_JSON ?= $(EVIDENCE_DIR)/wake-host-current-base-gate.json
PHASE3_REAL_MEDIA_CONTINUITY_JSON ?= $(EVIDENCE_DIR)/real-media-continuity.json
PHASE3_ADAPTIVE_MEDIA_REPORT ?= $(EVIDENCE_DIR)/adaptive-media-fluctuation.json
PHASE3_ADAPTIVE_MEDIA_CURRENT_BASE_JSON ?= $(EVIDENCE_DIR)/adaptive-media-current-base.json
PHASE3_ANDROID_UI_EVIDENCE ?=
PHASE3_ANDROID_UI_EVIDENCE_KIND ?= device_screenshot
PHASE3_ANDROID_UI_NOTE ?=
PHASE3_ADVANCED_DATACHANNEL_MANIFEST_JSON ?= $(EVIDENCE_DIR)/advanced-datachannel-manifest.json
PHASE3_ADVANCED_DATACHANNEL_WRITE_DEFAULT ?= 0
PHASE3_ADVANCED_DATACHANNEL_TREE_STATUS ?= $(shell if test -z "$$(git status --porcelain)"; then printf clean; else printf dirty; fi)

.PHONY: \
	protocol \
	protocol-tests \
	phase3-test \
	phase3-go-test \
	phase3-coturn-reconciliation-product-slice \
	phase3-authority-container-test \
	phase3-local-synthetic-product-e2e \
	phase3-local-synthetic-public-artifacts-check \
	phase3-local-product-e2e \
	phase3-real-media-continuity \
	phase3-real-media-current-base \
	phase3-adaptive-media-current-base \
	phase3-advanced-datachannel-current-base \
	phase3-advanced-datachannel-blocked-baseline \
	phase3-internet-soak-manifest \
	phase3-internet-soak-gate \
	phase3-internet-release-gate \
	baseline-macos-build \
	baseline-macos-xctest-preflight \
	baseline-macos-test \
	baseline-macos-self-test \
	baseline-macos-app \
	baseline-macos-dev-install \
	baseline-macos-host-preflight \
	baseline-macos-host-readiness \
	baseline-macos-touch-preflight \
	baseline-android-test \
	baseline-android-protocol-side-effect-owner \
	baseline-android-transport-boundary \
	baseline-android-check \
	baseline-android-apk \
	baseline-android-dependency-audit \
	evidence-tools-test \
	release-tools-test \
	file-transfer-android-smoke \
	phase0-stable-release-gate \
	require-evidence-serial \
	require-host-pid \
	evidence-device-info \
	evidence-usb-live-smoke \
	evidence-usb-smoke-preflight \
	evidence-touch-rerun-preflight \
	evidence-touch-rerun-summary \
	evidence-trusted-lan-preflight \
	trusted-lan-smoke-evidence-check \
	evidence-reconnect-timing-gate \
	evidence-reconnect-timing-blocked \
	evidence-latency-preflight \
	evidence-latency-gate \
	android-audio-current-base-readiness \
	android-audio-playback-gate \
	android-audio-playback-owner-record \
	native-pointer-hid-acceptance \
	native-pointer-hid-gate \
	physical-stylus-acceptance \
	physical-stylus-gate \
	actionable-error-states-gate \
	actionable-error-current-base-gate \
	actionable-error-current-base-owner-record \
	harmony-readiness \
	harmony-hap-readiness \
	harmony-device-gate \
	harmony-secure-pairing-gate \
	harmony-host-interop-preflight \
	harmony-host-interop-gate \
	harmony-avcodec-preflight \
	harmony-avcodec-validate \
	harmony-host-interop-preflight \
	harmony-host-interop-gate \
	harmony-current-base-gate \
	harmony-matepad-acceptance \
	soak-30m \
	soak-2h \
	soak-8h \
	host-rss-gate \
	soak-2h-host-rss-gate \
	phase2-tablet-manifest \
	phase2-device-memory-gate \
	phase2-tablet-gate \
	hardware-keyboard-readiness \
	hardware-keyboard-gate \
	phase2-tablet-preflight \
	phase2-macos-startup-recovery-gate \
	phase2-aggregate-owner \
	ios-app-signing-readiness-gate \
	ios-app-signing-current-base-gate \
	ios-device-acceptance-gate \
	ios-hdr-edr-gate \
	ios-native-input-gate \
	ios-current-base-manifest \
	ios-current-base-gate \
	phase5-multi-client-current-base-gate \
	macos-hardware-compatibility-gate \
	phase2-tablet-soak-preflight \
	phase2-tablet-soak-run \
	phase2-device-environment-summary \
	phase2-device-environment-gate \
	phase3-android-current-base-interop-gate \
	phase3-internet-soak-manifest \
	phase3-internet-soak-gate \
	host-display-rotation-gate \
	host-display-rotation-current-base-manifest \
	host-display-rotation-current-base-gate \
	wake-host-current-base-gate

protocol:
	cd contracts && $(BUF) format --diff --exit-code
	cd contracts && $(BUF) lint
	cd contracts && $(BUF) build
	cd contracts && $(BUF) breaking --against fixtures/v1.binpb
	$(MAKE) protocol-tests

protocol-tests:
	PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s contracts/tests -p 'test_*.py' -v

phase3-test: phase3-go-test
	PYTHONDONTWRITEBYTECODE=1 python3 scripts/phase3/release_gate_manifest.py --print-matrix >/dev/null
	PYTHONDONTWRITEBYTECODE=1 python3 scripts/phase3/network_recovery_blocked_evidence.py --output-dir .build/phase3-network-recovery-blocked-smoke >/dev/null
	$(MAKE) phase3-coturn-reconciliation-product-slice
	PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/phase3 -p 'test_*.py' -v
	PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/phase3_webrtc -p 'test_*.py' -v
	PYTHONDONTWRITEBYTECODE=1 python3 scripts/phase3/evidence_privacy.py --evidence-dir docs/changes/2026-08-04-phase-3-secure-internet/evidence/2026-08-05-nubia-p0110-internet --check
	PYTHONDONTWRITEBYTECODE=1 python3 scripts/phase3/session_authority_readiness.py --report docs/changes/2026-08-04-phase-3-secure-internet/evidence/2026-08-25-authority-turn-readiness-current-base-blocked/session-authority-readiness.json --write-summary .build/phase3-session-authority-readiness-summary.json || test "$$?" = 4
	PYTHONDONTWRITEBYTECODE=1 python3 scripts/phase3/public_nat_turn_preflight.py --relay-config deploy/phase3/config/relay.production.example.json --coturn-config deploy/phase3/coturn/production.conf --skip-dns-resolution --output .build/phase3-public-nat-turn-preflight.json --allow-blocked
	PYTHONDONTWRITEBYTECODE=1 python3 scripts/phase3/release_gate_summary.py --output .build/phase3-release-gate-summary.json

phase3-go-test:
	cd packages/security && test -z "$$(gofmt -l .)" && go vet ./... && go test -race -count=1 ./...
	$(MAKE) -C services/signaling verify
	$(MAKE) -C services/relay verify
	$(MAKE) -C services/authority verify

phase3-coturn-reconciliation-product-slice:
	PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile scripts/phase3/coturn_allocation_exporter.py scripts/phase3/coturn_reconciliation_loop.py scripts/phase3/coturn_disconnect_executor.py
	PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/phase3/test_coturn_allocation_exporter.py tests/phase3/test_coturn_reconciliation_loop.py tests/phase3/test_coturn_disconnect_executor.py -v

phase3-authority-container-test:
	deploy/phase3/scripts/test-authority-stack.sh

phase3-local-synthetic-product-e2e:
	@test -n "$(strip $(PHASE3_TURNSERVER))" || (echo "error: turnserver is unavailable; install coturn or set PHASE3_TURNSERVER" >&2; exit 2)
	@test -x "$(PHASE3_TURNSERVER)" || (echo "error: PHASE3_TURNSERVER is not executable: $(PHASE3_TURNSERVER)" >&2; exit 2)
	@command -v jq >/dev/null || (echo "error: jq is required for Phase 3 E2E assertions" >&2; exit 2)
	@coturn_version="$$($(PHASE3_TURNSERVER) --version 2>&1 | awk '/^[0-9]+\.[0-9]+\.[0-9]+$$/ { version=$$0 } END { print version }')"; case " $(PHASE3_COTURN_COMPATIBLE_VERSIONS) " in *" $$coturn_version "*) ;; *) echo "error: unsupported coturn version: $$coturn_version" >&2; exit 2;; esac
	mkdir -p "$(PHASE3_LOCAL_SYNTHETIC_E2E_DIR)"
	rm -f "$(PHASE3_LOCAL_SYNTHETIC_E2E_DIR)/direct.json" "$(PHASE3_LOCAL_SYNTHETIC_E2E_DIR)/relay.json"
	rm -rf "$(PHASE3_LOCAL_SYNTHETIC_E2E_DIR)/direct-logs" "$(PHASE3_LOCAL_SYNTHETIC_E2E_DIR)/relay-logs" "$(PHASE3_LOCAL_SYNTHETIC_E2E_PUBLIC_DIR)"
	PYTHONDONTWRITEBYTECODE=1 python3 scripts/phase3_webrtc/run_local_e2e.py --mode direct --slice product --timeout-seconds "$(PHASE3_LOCAL_SYNTHETIC_E2E_TIMEOUT_SECONDS)" --diagnostics-dir "$(PHASE3_LOCAL_SYNTHETIC_E2E_DIR)/direct-logs" --output "$(PHASE3_LOCAL_SYNTHETIC_E2E_DIR)/direct.json"
	@jq -e 'select(.schema == "$(PHASE3_WEBRTC_E2E_SCHEMA)" and .result == "pass" and .mode == "direct" and .slice == "product" and .signaling.real_process == true and .webrtc.selected_route == "direct" and (.webrtc.selected_candidate_pair | startswith("direct(")) and .product_session.host == "InternetProductSession" and .product_session.device == "synthetic Protocol v1 harness" and .product_session.media_source == "videotoolbox-hevc" and .product_session.capture_or_stream_server_started == false)' "$(PHASE3_LOCAL_SYNTHETIC_E2E_DIR)/direct.json" >/dev/null
	PYTHONDONTWRITEBYTECODE=1 python3 scripts/phase3_webrtc/run_local_e2e.py --mode relay --slice product --skip-build --turnserver "$(PHASE3_TURNSERVER)" --timeout-seconds "$(PHASE3_LOCAL_SYNTHETIC_E2E_TIMEOUT_SECONDS)" --diagnostics-dir "$(PHASE3_LOCAL_SYNTHETIC_E2E_DIR)/relay-logs" --output "$(PHASE3_LOCAL_SYNTHETIC_E2E_DIR)/relay.json"
	@jq -e 'select(.schema == "$(PHASE3_WEBRTC_E2E_SCHEMA)" and .result == "pass" and .mode == "relay" and .slice == "product" and .signaling.real_process == true and .webrtc.selected_route == "relay" and (.webrtc.selected_candidate_pair | startswith("relay(")) and .coturn.real_process == true and .coturn.forced_libwebrtc_relay == "pass" and .product_session.host == "InternetProductSession" and .product_session.device == "synthetic Protocol v1 harness" and .product_session.media_source == "videotoolbox-hevc" and .product_session.capture_or_stream_server_started == false)' "$(PHASE3_LOCAL_SYNTHETIC_E2E_DIR)/relay.json" >/dev/null
	$(MAKE) phase3-local-synthetic-public-artifacts-check

phase3-local-synthetic-public-artifacts-check:
	PYTHONDONTWRITEBYTECODE=1 python3 scripts/phase3_webrtc/public_artifacts.py --root "$(PHASE3_LOCAL_SYNTHETIC_E2E_DIR)" --output "$(PHASE3_LOCAL_SYNTHETIC_E2E_PUBLIC_DIR)"

phase3-local-product-e2e:
	@printf '%s\n' 'warning: phase3-local-product-e2e is deprecated; use phase3-local-synthetic-product-e2e (synthetic Protocol v1 harness with real VideoToolbox HEVC payloads only; no Android device, ScreenCaptureKit capture, or MediaCodec decode).' >&2
	@$(MAKE) phase3-local-synthetic-product-e2e

phase3-real-media-continuity:
	@test -n "$(strip $(EVIDENCE_DIR))" || (echo "error: set EVIDENCE_DIR" >&2; exit 2)
	@test -n "$(strip $(PHASE3_HOST_LOG))" || (echo "error: set PHASE3_HOST_LOG to retained Host log evidence" >&2; exit 2)
	@test -n "$(strip $(PHASE3_ANDROID_LOG))" || (echo "error: set PHASE3_ANDROID_LOG to retained Android log evidence" >&2; exit 2)
	@test -f "$(PHASE3_HOST_LOG)" && test -r "$(PHASE3_HOST_LOG)" || (echo "error: PHASE3_HOST_LOG is not a readable file" >&2; exit 2)
	@test -f "$(PHASE3_ANDROID_LOG)" && test -r "$(PHASE3_ANDROID_LOG)" || (echo "error: PHASE3_ANDROID_LOG is not a readable file" >&2; exit 2)
	@if test -n "$(strip $(PHASE3_DEVICE_INFO))"; then \
		test -f "$(PHASE3_DEVICE_INFO)" && test -r "$(PHASE3_DEVICE_INFO)" || (echo "error: PHASE3_DEVICE_INFO is not a readable file" >&2; exit 2); \
	fi
	mkdir -p "$(EVIDENCE_DIR)"
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools \
		python3 -m vibescreen_evidence.phase3_real_media_continuity \
		--host-log "$(PHASE3_HOST_LOG)" \
		--android-log "$(PHASE3_ANDROID_LOG)" \
		--network-path "$(PHASE3_NETWORK_PATH)" \
		--host-signing "$(PHASE3_HOST_SIGNING)" \
		--screen-recording "$(PHASE3_SCREEN_RECORDING)" \
		--minimum-output-frames "$(PHASE3_MINIMUM_OUTPUT_FRAMES)" \
		--maximum-dropped-frames "$(PHASE3_MAXIMUM_DROPPED_FRAMES)" \
		$(if $(strip $(PHASE3_DEVICE_INFO)),--device-info "$(PHASE3_DEVICE_INFO)",) \
		--output "$(EVIDENCE_DIR)/real-media-continuity.json"

phase3-real-media-current-base:
	@test -n "$(strip $(EVIDENCE_DIR))" || (echo "error: set EVIDENCE_DIR" >&2; exit 2)
	@test -n "$(strip $(PHASE3_REAL_MEDIA_CONTINUITY_JSON))" || (echo "error: set PHASE3_REAL_MEDIA_CONTINUITY_JSON" >&2; exit 2)
	@test -f "$(PHASE3_REAL_MEDIA_CONTINUITY_JSON)" && test -r "$(PHASE3_REAL_MEDIA_CONTINUITY_JSON)" || (echo "error: PHASE3_REAL_MEDIA_CONTINUITY_JSON is not a readable file" >&2; exit 2)
	@if test -n "$(strip $(PHASE3_ANDROID_UI_EVIDENCE))"; then \
		test -f "$(PHASE3_ANDROID_UI_EVIDENCE)" && test -r "$(PHASE3_ANDROID_UI_EVIDENCE)" || (echo "error: PHASE3_ANDROID_UI_EVIDENCE is not a readable file" >&2; exit 2); \
	fi
	mkdir -p "$(EVIDENCE_DIR)"
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools \
		python3 -m vibescreen_evidence.phase3_real_media_current_base \
		--continuity-result "$(PHASE3_REAL_MEDIA_CONTINUITY_JSON)" \
		$(if $(strip $(PHASE3_ANDROID_UI_EVIDENCE)),--android-ui-evidence "$(PHASE3_ANDROID_UI_EVIDENCE)",) \
		--android-ui-evidence-kind "$(PHASE3_ANDROID_UI_EVIDENCE_KIND)" \
		$(if $(strip $(PHASE3_ANDROID_UI_NOTE)),--android-ui-note "$(PHASE3_ANDROID_UI_NOTE)",) \
		--output "$(EVIDENCE_DIR)/current-base-real-media.json"

phase3-adaptive-media-current-base:
	@test -n "$(strip $(EVIDENCE_DIR))" || (echo "error: set EVIDENCE_DIR" >&2; exit 2)
	@test -n "$(strip $(PHASE3_ADAPTIVE_MEDIA_REPORT))" || (echo "error: set PHASE3_ADAPTIVE_MEDIA_REPORT" >&2; exit 2)
	@test -f "$(PHASE3_ADAPTIVE_MEDIA_REPORT)" && test -r "$(PHASE3_ADAPTIVE_MEDIA_REPORT)" || (echo "error: PHASE3_ADAPTIVE_MEDIA_REPORT is not a readable file" >&2; exit 2)
	mkdir -p "$(EVIDENCE_DIR)"
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools \
		python3 -m vibescreen_evidence.phase3_adaptive_media_current_base \
		--report "$(PHASE3_ADAPTIVE_MEDIA_REPORT)" \
		--repo . \
		--output "$(PHASE3_ADAPTIVE_MEDIA_CURRENT_BASE_JSON)"

phase3-advanced-datachannel-current-base:
	@test -n "$(strip $(EVIDENCE_DIR))" || (echo "error: set EVIDENCE_DIR" >&2; exit 2)
	@if ! echo " 1 true yes " | grep -q " $(PHASE3_ADVANCED_DATACHANNEL_WRITE_DEFAULT) "; then \
		test -f "$(PHASE3_ADVANCED_DATACHANNEL_MANIFEST_JSON)" || (echo "error: set PHASE3_ADVANCED_DATACHANNEL_MANIFEST_JSON to retained evidence or run phase3-advanced-datachannel-blocked-baseline" >&2; exit 2); \
	fi
	mkdir -p "$(EVIDENCE_DIR)"
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools \
		python3 -m vibescreen_evidence.phase3_advanced_datachannel_current_base \
		--manifest "$(PHASE3_ADVANCED_DATACHANNEL_MANIFEST_JSON)" \
		--output "$(EVIDENCE_DIR)/advanced-datachannel-current-base.json" \
		--repo "." \
		--source-commit "$$(git rev-parse HEAD)" \
		--tree-status "$(PHASE3_ADVANCED_DATACHANNEL_TREE_STATUS)" \
		$(if $(filter 1 true yes,$(PHASE3_ADVANCED_DATACHANNEL_WRITE_DEFAULT)),--write-default-manifest,)

phase3-advanced-datachannel-blocked-baseline:
	$(MAKE) phase3-advanced-datachannel-current-base PHASE3_ADVANCED_DATACHANNEL_WRITE_DEFAULT=1

phase3-internet-soak-manifest:
	@test -n "$(strip $(EVIDENCE_DIR))" || (echo "error: set EVIDENCE_DIR to a Phase 3 Internet soak evidence directory" >&2; exit 2)
	@test -n "$(strip $(PHASE3_INTERNET_TURN_URI) $(PHASE3_INTERNET_TURN_URIS))" || (echo "error: set PHASE3_INTERNET_TURN_URI or PHASE3_INTERNET_TURN_URIS to a public turns:?transport=tcp URI" >&2; exit 2)
	@test -n "$(strip $(PHASE3_INTERNET_SIGNALING_ORIGIN))" || (echo "error: set PHASE3_INTERNET_SIGNALING_ORIGIN to the public signaling HTTPS origin" >&2; exit 2)
	@test -n "$(strip $(PHASE3_INTERNET_RELAY_ORIGIN))" || (echo "error: set PHASE3_INTERNET_RELAY_ORIGIN to the public relay HTTPS origin" >&2; exit 2)
	@test -n "$(strip $(PHASE3_INTERNET_AUTHORITY_SOURCE_ID))" || (echo "error: set PHASE3_INTERNET_AUTHORITY_SOURCE_ID" >&2; exit 2)
	@test -n "$(strip $(PHASE3_INTERNET_REMOTE_PEER))" || (echo "error: set PHASE3_INTERNET_REMOTE_PEER to an independent public peer" >&2; exit 2)
	@test -n "$(strip $(PHASE3_INTERNET_TLS_CERTIFICATE_SHA256))" || (echo "error: set PHASE3_INTERNET_TLS_CERTIFICATE_SHA256" >&2; exit 2)
	@test -n "$(strip $(PHASE3_INTERNET_TURN_SECRET_SOURCE))" || (echo "error: set PHASE3_INTERNET_TURN_SECRET_SOURCE to file or secret_manager" >&2; exit 2)
	@test -n "$(strip $(PHASE3_INTERNET_DEPLOYMENT_READINESS))" || (echo "error: set PHASE3_INTERNET_DEPLOYMENT_READINESS" >&2; exit 2)
	@test -n "$(strip $(PHASE3_INTERNET_PLANNED_HANDOFFS))" || (echo "error: set PHASE3_INTERNET_PLANNED_HANDOFFS" >&2; exit 2)
	@test -n "$(strip $(PHASE3_INTERNET_HOST_BUILD))" || (echo "error: set PHASE3_INTERNET_HOST_BUILD" >&2; exit 2)
	@test -n "$(strip $(PHASE3_INTERNET_ANDROID_ARTIFACT_SHA256))" || (echo "error: set PHASE3_INTERNET_ANDROID_ARTIFACT_SHA256" >&2; exit 2)
	mkdir -p "$(dir $(PHASE3_INTERNET_SOAK_MANIFEST))"
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools \
		python3 -m vibescreen_evidence.phase3_internet_soak manifest \
		--output "$(PHASE3_INTERNET_SOAK_MANIFEST)" \
		--repo . \
		$(foreach uri,$(PHASE3_INTERNET_TURN_URI) $(PHASE3_INTERNET_TURN_URIS),--turn-uri "$(uri)") \
		--signaling-origin "$(PHASE3_INTERNET_SIGNALING_ORIGIN)" \
		--relay-origin "$(PHASE3_INTERNET_RELAY_ORIGIN)" \
		--authority-source-id "$(PHASE3_INTERNET_AUTHORITY_SOURCE_ID)" \
		--remote-peer "$(PHASE3_INTERNET_REMOTE_PEER)" \
		--tls-certificate-sha256 "$(PHASE3_INTERNET_TLS_CERTIFICATE_SHA256)" \
		--turn-secret-source "$(PHASE3_INTERNET_TURN_SECRET_SOURCE)" \
		--deployment-readiness "$(PHASE3_INTERNET_DEPLOYMENT_READINESS)" \
		--planned-handoffs "$(PHASE3_INTERNET_PLANNED_HANDOFFS)" \
		--host-build "$(PHASE3_INTERNET_HOST_BUILD)" \
		--android-artifact-sha256 "$(PHASE3_INTERNET_ANDROID_ARTIFACT_SHA256)" \
		--duration-seconds "$(PHASE3_INTERNET_DURATION_SECONDS)" \
		--sample-interval-seconds "$(PHASE3_INTERNET_SAMPLE_INTERVAL_SECONDS)" \
		$(if $(strip $(PHASE3_INTERNET_NOTES)),--notes "$(PHASE3_INTERNET_NOTES)",) \
		-- make phase3-internet-soak-gate EVIDENCE_DIR=$(EVIDENCE_DIR)

phase3-internet-soak-gate:
	@test -n "$(strip $(EVIDENCE_DIR))" || (echo "error: set EVIDENCE_DIR to a Phase 3 Internet soak evidence directory" >&2; exit 2)
	mkdir -p "$(dir $(PHASE3_INTERNET_SOAK_GATE_JSON))"
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools \
		python3 -m vibescreen_evidence.phase3_internet_soak gate \
		--output "$(PHASE3_INTERNET_SOAK_GATE_JSON)" \
		--manifest "$(PHASE3_INTERNET_SOAK_MANIFEST)" \
		--remote-turn "$(PHASE3_INTERNET_REMOTE_TURN_REPORT)" \
		--media-continuity "$(PHASE3_INTERNET_MEDIA_CONTINUITY_REPORT)" \
		--network-handoff "$(PHASE3_INTERNET_NETWORK_HANDOFF_REPORT)" \
		--revocation "$(PHASE3_INTERNET_REVOCATION_REPORT)" \
		--soak-report "$(PHASE3_INTERNET_SOAK_REPORT)" \
		$(if $(strip $(PHASE3_INTERNET_BLOCKED_REASON)),--blocked-reason "$(PHASE3_INTERNET_BLOCKED_REASON)",) \
		$(if $(filter 1 true yes,$(PHASE3_INTERNET_ALLOW_BLOCKED)),--allow-blocked,)

phase3-internet-release-gate:
	@test -n "$(strip $(EVIDENCE_DIR))" || (echo "error: set EVIDENCE_DIR to a Phase 3 Internet evidence directory" >&2; exit 2)
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools \
		python3 -m vibescreen_evidence.phase3_internet_release_gate \
		--evidence-dir "$(EVIDENCE_DIR)"

phase3-android-current-base-interop-gate:
	@test -n "$(strip $(PHASE3_ANDROID_INTEROP_EVIDENCE))" || (echo "error: set PHASE3_ANDROID_INTEROP_EVIDENCE to a Phase 3 Android interop evidence JSON" >&2; exit 2)
	mkdir -p "$(EVIDENCE_DIR)"
	PYTHONDONTWRITEBYTECODE=1 python3 scripts/phase3/android_current_base_interop_gate.py --evidence "$(PHASE3_ANDROID_INTEROP_EVIDENCE)" --profile "$(PHASE3_ANDROID_INTEROP_GATE_PROFILE)" --output "$(EVIDENCE_DIR)/phase3-android-current-base-interop-gate.json"

baseline-macos-build:
	cd baseline/MacHost && swift build -c release

baseline-macos-xctest-preflight:
	python3 scripts/macos_dev_host.py xctest-preflight

baseline-macos-test: baseline-macos-xctest-preflight
	cd baseline/MacHost && swift test

baseline-macos-self-test: baseline-macos-build
	@host_bin="$$(cd baseline/MacHost && swift build -c release --show-bin-path)/Vibe Screen"; \
		"$$host_bin" --host-self-test; \
		"$$host_bin" --transport-self-test; \
		"$$host_bin" --reliability-self-test; \
		"$$host_bin" --protocol-v1-self-test; \
		"$$host_bin" --audio-capture-self-test; \
		"$$host_bin" --video-encoder-self-test; \
		"$$host_bin" --phase3-real-media-self-test

baseline-macos-app:
	python3 scripts/package_macos.py

baseline-macos-dev-install:
	python3 scripts/macos_dev_host.py install

baseline-macos-host-preflight:
	python3 scripts/macos_dev_host.py preflight

baseline-macos-host-readiness:
	mkdir -p $(EVIDENCE_DIR)
	python3 scripts/macos_dev_host.py readiness \
		--report $(EVIDENCE_DIR)/host-signing-and-permissions.txt \
		--json-output $(EVIDENCE_DIR)/host-readiness.json \
		--port $(EVIDENCE_PORT) \
		$(if $(filter 1 true yes,$(MACOS_HOST_READINESS_PROBE_LOGIN_ITEM)),--include-login-item-diagnostic,)

baseline-macos-touch-preflight: baseline-macos-host-preflight

baseline-android-test:
	cd baseline/AndroidClient && ./gradlew :transport:check testDebugUnitTest

baseline-android-protocol-side-effect-owner:
	cd baseline/AndroidClient && ./gradlew --no-daemon testDebugUnitTest \
		--tests dev.telemachus.display.StreamProtocolSideEffectOwnerTest \
		--tests dev.telemachus.display.StreamClientOwnershipBoundaryContractTest \
		--tests dev.telemachus.display.StreamProtocolActionDispatcherTest \
		--tests dev.telemachus.display.WakeHostTest \
		--tests "dev.telemachus.display.StreamClientProtocolV1IntegrationTest.signedWakeHostRequestSendsMagicPacketAndRejectsReplay" \
		--tests "dev.telemachus.display.StreamClientProtocolV1IntegrationTest.queuedWakeHostRequestAfterDisconnectDoesNotSendPacketOrResult" \
		--tests "dev.telemachus.display.StreamClientProtocolV1IntegrationTest.staleHostFileOfferDecisionAfterDisconnectSendsNoAccept" \
		--tests "dev.telemachus.display.StreamClientProtocolV1IntegrationTest.unsignedWakeHostRequestFailsClosedWithoutSendingPacket"

baseline-android-transport-boundary:
	cd baseline/AndroidClient && ./gradlew :transport:check --configuration-cache --configuration-cache-problems=fail

baseline-android-check: baseline-android-transport-boundary
	cd baseline/AndroidClient && ./gradlew testDebugUnitTest lintDebug assembleDebug auditReleaseDependencies

baseline-android-apk:
	cd baseline/AndroidClient && ./gradlew assembleDebug

baseline-android-dependency-audit:
	cd baseline/AndroidClient && ./gradlew auditReleaseDependencies

evidence-tools-test:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest discover -s tools/tests -v

release-tools-test:
	PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts/tests -v

phase0-stable-release-gate:
	@test -f "$(PHASE0_STABLE_RELEASE_MANIFEST)" || (echo "error: missing Phase 0 stable-release manifest: $(PHASE0_STABLE_RELEASE_MANIFEST)" >&2; exit 2)
	mkdir -p "$(dir $(PHASE0_STABLE_RELEASE_SUMMARY))"
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.phase0_stable_release \
		--manifest "$(PHASE0_STABLE_RELEASE_MANIFEST)" \
		--readme README.md \
		--output "$(PHASE0_STABLE_RELEASE_SUMMARY)" \
		$(if $(strip $(PHASE0_STABLE_RELEASE_EXPECTED_SOURCE_COMMIT)),--expected-source-commit "$(PHASE0_STABLE_RELEASE_EXPECTED_SOURCE_COMMIT)",) \
		$(if $(strip $(PHASE0_STABLE_RELEASE_REQUIRE_PASS)),--require-pass,)

require-evidence-serial:
	@test -n "$(strip $(EVIDENCE_SERIAL))" || (echo "error: set EVIDENCE_SERIAL explicitly" >&2; exit 2)

require-host-pid:
	@test -n "$(strip $(EVIDENCE_HOST_PID))" || (echo "error: set HOST_PID or EVIDENCE_HOST_PID to the running Vibe Screen Host process id" >&2; exit 2)

evidence-device-info: require-evidence-serial
	mkdir -p $(EVIDENCE_DIR)
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.device_info --serial $(EVIDENCE_SERIAL) --package $(EVIDENCE_PACKAGE) --output $(EVIDENCE_DIR)/device-info.json

evidence-usb-live-smoke: require-evidence-serial
	mkdir -p $(EVIDENCE_DIR)
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.usb_live_smoke --serial $(EVIDENCE_SERIAL) --package $(EVIDENCE_PACKAGE) --port $(EVIDENCE_PORT) --output $(EVIDENCE_DIR)/usb-live-smoke.json

evidence-usb-smoke-preflight: require-evidence-serial
	mkdir -p $(EVIDENCE_DIR)
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.usb_smoke_preflight \
		--serial $(EVIDENCE_SERIAL) \
		--package $(EVIDENCE_PACKAGE) \
		--port $(EVIDENCE_PORT) \
		$(if $(strip $(EVIDENCE_EXPECTED_MANUFACTURER)),--expected-manufacturer $(EVIDENCE_EXPECTED_MANUFACTURER),) \
		$(if $(strip $(EVIDENCE_EXPECTED_MODEL)),--expected-model $(EVIDENCE_EXPECTED_MODEL),) \
		$(if $(strip $(EVIDENCE_EXPECTED_DEVICE)),--expected-device $(EVIDENCE_EXPECTED_DEVICE),) \
		$(if $(strip $(EVIDENCE_EXPECTED_ANDROID_RELEASE)),--expected-android-release $(EVIDENCE_EXPECTED_ANDROID_RELEASE),) \
		$(if $(strip $(EVIDENCE_EXPECTED_SDK)),--expected-sdk $(EVIDENCE_EXPECTED_SDK),) \
		$(if $(filter 1 true yes,$(EVIDENCE_ALLOW_EXISTING_LOCKS)),--allow-existing-locks,) \
		--output $(EVIDENCE_DIR)/usb-smoke-preflight.json

evidence-touch-rerun-preflight: require-evidence-serial
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools \
		python3 -m vibescreen_evidence.touch_rerun_preflight \
		--serial $(EVIDENCE_SERIAL) \
		$(if $(strip $(TOUCH_RERUN_EXPECTED_HOST_SHA256)),--expected-host-sha256 $(TOUCH_RERUN_EXPECTED_HOST_SHA256),) \
		$(if $(strip $(TOUCH_RERUN_EXPECTED_ANDROID_MANUFACTURER)),--expected-android-manufacturer $(TOUCH_RERUN_EXPECTED_ANDROID_MANUFACTURER),) \
		$(if $(strip $(TOUCH_RERUN_EXPECTED_ANDROID_MODEL)),--expected-android-model $(TOUCH_RERUN_EXPECTED_ANDROID_MODEL),) \
		$(if $(strip $(TOUCH_RERUN_EXPECTED_ANDROID_DEVICE)),--expected-android-device $(TOUCH_RERUN_EXPECTED_ANDROID_DEVICE),) \
		$(if $(strip $(TOUCH_RERUN_EXPECTED_ANDROID_RELEASE)),--expected-android-release $(TOUCH_RERUN_EXPECTED_ANDROID_RELEASE),) \
		$(if $(strip $(TOUCH_RERUN_EXPECTED_ANDROID_SDK)),--expected-android-sdk $(TOUCH_RERUN_EXPECTED_ANDROID_SDK),) \
		$(if $(filter 1 true yes,$(TOUCH_RERUN_REQUIRE_CURRENT_SOURCE)),--source-root . --require-current-source,) \
		--output $(TOUCH_RERUN_PREFLIGHT)

evidence-touch-rerun-summary:
	@test -n "$(strip $(EVIDENCE_DIR))" || (echo "error: set EVIDENCE_DIR to a touch rerun evidence directory" >&2; exit 2)
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools \
		python3 -m vibescreen_evidence.touch_rerun_summary \
		--preflight $(TOUCH_RERUN_PREFLIGHT) \
		--instrumentation $(TOUCH_RERUN_INSTRUMENTATION) \
		--host-log $(TOUCH_RERUN_HOST_LOG) \
		--event-tap $(TOUCH_RERUN_EVENT_TAP) \
		$(if $(strip $(TOUCH_RERUN_EXPECTED_ANDROID_MANUFACTURER)),--expected-android-manufacturer $(TOUCH_RERUN_EXPECTED_ANDROID_MANUFACTURER),) \
		$(if $(strip $(TOUCH_RERUN_EXPECTED_ANDROID_MODEL)),--expected-android-model $(TOUCH_RERUN_EXPECTED_ANDROID_MODEL),) \
		$(if $(strip $(TOUCH_RERUN_EXPECTED_ANDROID_DEVICE)),--expected-android-device $(TOUCH_RERUN_EXPECTED_ANDROID_DEVICE),) \
		$(if $(strip $(TOUCH_RERUN_EXPECTED_ANDROID_RELEASE)),--expected-android-release $(TOUCH_RERUN_EXPECTED_ANDROID_RELEASE),) \
		$(if $(strip $(TOUCH_RERUN_EXPECTED_ANDROID_SDK)),--expected-android-sdk $(TOUCH_RERUN_EXPECTED_ANDROID_SDK),) \
		--output $(EVIDENCE_DIR)/result-summary.json

evidence-trusted-lan-preflight: require-evidence-serial
	mkdir -p $(EVIDENCE_DIR)
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools \
		python3 -m vibescreen_evidence.trusted_lan_preflight \
		--serial $(EVIDENCE_SERIAL) \
		--repo . \
		--host-port $(TRUSTED_LAN_HOST_PORT) \
		$(if $(strip $(TRUSTED_LAN_HOST_IPV4)),--mac-host-ipv4 $(TRUSTED_LAN_HOST_IPV4),) \
		$(if $(strip $(TRUSTED_LAN_REQUIRE_HOST_LISTENER)),--require-host-listener,) \
		--output $(EVIDENCE_DIR)/trusted-lan-preflight.json

trusted-lan-smoke-evidence-check:
	@test -n "$(strip $(EVIDENCE_DIR))" || (echo "error: set EVIDENCE_DIR to a trusted-LAN smoke evidence directory" >&2; exit 2)
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools \
		python3 -m vibescreen_evidence.trusted_lan_smoke \
		--evidence-dir $(EVIDENCE_DIR) \
		--output $(EVIDENCE_DIR)/trusted-lan-smoke-verdict.json

evidence-reconnect-timing-gate:
	@test -n "$(strip $(EVIDENCE_DIR))" || (echo "error: set EVIDENCE_DIR to a reconnect timing evidence directory" >&2; exit 2)
	@test -f "$(RECONNECT_TIMING_OBSERVATIONS_JSON)" || (echo "error: missing reconnect timing observations: $(RECONNECT_TIMING_OBSERVATIONS_JSON)" >&2; exit 2)
	mkdir -p $(EVIDENCE_DIR)
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools \
		python3 -m vibescreen_evidence.reconnect_timing \
		$(RECONNECT_TIMING_OBSERVATIONS_JSON) \
		$(foreach disruption,$(RECONNECT_TIMING_REQUIRE_DISRUPTIONS),--require-disruption $(disruption)) \
		--base-dir $(EVIDENCE_DIR) \
		--output $(EVIDENCE_DIR)/reconnect-timing-summary.json

evidence-reconnect-timing-blocked: require-evidence-serial
	@test -n "$(strip $(EVIDENCE_DIR))" || (echo "error: set EVIDENCE_DIR to a reconnect timing evidence directory" >&2; exit 2)
	mkdir -p $(EVIDENCE_DIR)
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools \
		python3 -m vibescreen_evidence.reconnect_timing \
		--blocked \
		--target-device "$(RECONNECT_TIMING_TARGET_DEVICE)" \
		$(RECONNECT_TIMING_BLOCKER_ARGS) \
		$(RECONNECT_TIMING_ARTIFACT_ARGS) \
		$(RECONNECT_TIMING_NOTES_ARG) \
		--output $(EVIDENCE_DIR)/reconnect-timing-summary.json || test $$? -eq 3

native-pointer-hid-acceptance: require-evidence-serial
	mkdir -p "$(EVIDENCE_DIR)"
	@set +e; \
	PYTHONDONTWRITEBYTECODE=1 python3 scripts/native_pointer_hid_acceptance.py \
		--serial "$(EVIDENCE_SERIAL)" \
		--host-log "$(NATIVE_POINTER_HOST_LOG)" \
		--observe-seconds $(NATIVE_POINTER_OBSERVE_SECONDS) \
		--visible-result-note "$(NATIVE_POINTER_VISIBLE_RESULT_NOTE)" \
		$(NATIVE_POINTER_HOST_READY_ARG) \
		--evidence-dir "$(EVIDENCE_DIR)" \
		--write-blocked-on-lock; \
	status=$$?; \
	if [ -f "$(EVIDENCE_DIR)/result.json" ] && [ ! -f "$(EVIDENCE_DIR)/native-pointer-hid-summary.json" ]; then \
		set +e; \
		PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.native_pointer_hid \
			"$(EVIDENCE_DIR)/result.json" \
			--output "$(EVIDENCE_DIR)/native-pointer-hid-summary.json"; \
		gate_status=$$?; \
		if [ $$gate_status -ne 0 ] && [ $$gate_status -ne 2 ]; then exit $$gate_status; fi; \
	fi; \
	exit $$status

native-pointer-hid-gate:
	@test -f "$(EVIDENCE_DIR)/result.json" || (echo "error: collect $(EVIDENCE_DIR)/result.json before native-pointer-hid-gate" >&2; exit 2)
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.native_pointer_hid "$(EVIDENCE_DIR)/result.json" --output "$(EVIDENCE_DIR)/native-pointer-hid-summary.json" --require-pass

physical-stylus-acceptance: require-evidence-serial
	mkdir -p "$(EVIDENCE_DIR)"
	PYTHONDONTWRITEBYTECODE=1 python3 scripts/android_stylus_acceptance.py \
		--serial "$(EVIDENCE_SERIAL)" \
		--output-dir "$(EVIDENCE_DIR)" \
		--host-log "$(STYLUS_HOST_LOG)" \
		--observe-seconds $(STYLUS_OBSERVE_SECONDS) \
		--drawing-observation "$(STYLUS_DRAWING_OBSERVATION)" \
		$(STYLUS_OBSERVED_PHYSICAL_DRAWING_ARG) \
		$(STYLUS_HOST_READY_ARG) \
		--write-blocked-on-lock

physical-stylus-gate:
	@test -f "$(EVIDENCE_DIR)/stylus-evidence.json" || (echo "error: collect $(EVIDENCE_DIR)/stylus-evidence.json before physical-stylus-gate" >&2; exit 2)
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.stylus "$(EVIDENCE_DIR)/stylus-evidence.json" --output "$(EVIDENCE_DIR)/stylus-summary.json" --require-pass

android-audio-current-base-readiness: require-evidence-serial
	mkdir -p "$(EVIDENCE_DIR)"
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 scripts/android_audio_current_base_readiness.py \
		--serial "$(EVIDENCE_SERIAL)" \
		--evidence-dir "$(EVIDENCE_DIR)" \
		--package "$(EVIDENCE_PACKAGE)" \
		--port "$(EVIDENCE_PORT)" \
		--logcat-lines "$(ANDROID_AUDIO_READINESS_LOGCAT_LINES)" \
		--max-log-bytes "$(ANDROID_AUDIO_READINESS_MAX_LOG_BYTES)"

android-audio-playback-gate:
	@test -f "$(ANDROID_AUDIO_PLAYBACK_JSON)" || (echo "error: collect $(ANDROID_AUDIO_PLAYBACK_JSON) before android-audio-playback-gate" >&2; exit 2)
	mkdir -p "$(dir $(ANDROID_AUDIO_PLAYBACK_GATE_JSON))"
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.android_audio_playback "$(ANDROID_AUDIO_PLAYBACK_JSON)" --evidence-dir "$(dir $(ANDROID_AUDIO_PLAYBACK_JSON))" --output "$(ANDROID_AUDIO_PLAYBACK_GATE_JSON)" --require-pass

android-audio-playback-owner-record:
	@test -f "$(ANDROID_AUDIO_PLAYBACK_JSON)" || (echo "error: collect $(ANDROID_AUDIO_PLAYBACK_JSON) before android-audio-playback-owner-record" >&2; exit 2)
	mkdir -p "$(dir $(ANDROID_AUDIO_PLAYBACK_GATE_JSON))"
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.android_audio_playback "$(ANDROID_AUDIO_PLAYBACK_JSON)" --evidence-dir "$(dir $(ANDROID_AUDIO_PLAYBACK_JSON))" --output "$(ANDROID_AUDIO_PLAYBACK_GATE_JSON)"

actionable-error-states-gate:
	mkdir -p $(EVIDENCE_DIR)
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.actionable_error_states \
		docs/changes/2026-08-23-actionable-error-states/actionable-error-states.json \
		--android-session-failure-source baseline/AndroidClient/app/src/main/java/dev/telemachus/display/SessionFailure.kt \
		--repository-root . \
		--output $(EVIDENCE_DIR)/actionable-error-states-gate.json

actionable-error-current-base-gate:
	@test -f "$(ACTIONABLE_ERROR_CURRENT_BASE_MANIFEST)" || (echo "error: set EVIDENCE_DIR or ACTIONABLE_ERROR_CURRENT_BASE_MANIFEST to the actionable-error-current-base.json path" >&2; exit 2)
	mkdir -p "$(dir $(ACTIONABLE_ERROR_CURRENT_BASE_GATE_JSON))"
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.actionable_error_current_base \
		--manifest "$(ACTIONABLE_ERROR_CURRENT_BASE_MANIFEST)" \
		--repository-root . \
		--output "$(ACTIONABLE_ERROR_CURRENT_BASE_GATE_JSON)"

actionable-error-current-base-owner-record:
	@test -f "$(ACTIONABLE_ERROR_CURRENT_BASE_MANIFEST)" || (echo "error: set EVIDENCE_DIR or ACTIONABLE_ERROR_CURRENT_BASE_MANIFEST to the actionable-error-current-base.json path" >&2; exit 2)
	mkdir -p "$(dir $(ACTIONABLE_ERROR_CURRENT_BASE_GATE_JSON))"
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.actionable_error_current_base \
		--manifest "$(ACTIONABLE_ERROR_CURRENT_BASE_MANIFEST)" \
		--repository-root . \
		--output "$(ACTIONABLE_ERROR_CURRENT_BASE_GATE_JSON)" \
		--allow-blocked

evidence-latency-preflight:
	mkdir -p $(EVIDENCE_DIR)
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools \
		python3 -m vibescreen_evidence.latency_preflight \
		$(if $(strip $(LATENCY_PREFLIGHT_INPUT)),--input $(LATENCY_PREFLIGHT_INPUT),) \
		$(if $(strip $(LATENCY_DEVICE_INFO)),--device-info $(LATENCY_DEVICE_INFO),) \
		$(if $(strip $(LATENCY_REPOSITORY_REVISION)),--repository-revision $(LATENCY_REPOSITORY_REVISION),) \
		--repo . \
		--output $(EVIDENCE_DIR)/latency-preflight.json; \
		status=$$?; printf '%s\n' "$$status" > $(EVIDENCE_DIR)/latency-preflight-exit.txt; exit $$status

evidence-latency-gate:
	@test -n "$(strip $(LATENCY_GATE_PROFILE))" || (echo "error: set LATENCY_GATE_PROFILE" >&2; exit 2)
	mkdir -p $(EVIDENCE_DIR)
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools \
		python3 -m vibescreen_evidence.latency_evidence \
		$(LATENCY_MANIFEST) \
		--gate-profile $(LATENCY_GATE_PROFILE) \
		--output $(EVIDENCE_DIR)/latency-evidence-report.json

harmony-readiness:
	@test -n "$(strip $(EVIDENCE_DIR))" || (echo "error: set EVIDENCE_DIR to a HarmonyOS readiness evidence directory" >&2; exit 2)
	mkdir -p $(EVIDENCE_DIR)
	PYTHONDONTWRITEBYTECODE=1 python3 scripts/harmony_readiness.py --output "$(EVIDENCE_DIR)/harmony-readiness.json" \
		$(if $(strip $(HARMONY_HDC_TARGET)),--target "$(HARMONY_HDC_TARGET)",) \
		$(if $(strip $(HARMONY_HAP)),--hap "$(HARMONY_HAP)",) \
		$(if $(strip $(HARMONY_SHA256SUMS)),--sha256sums "$(HARMONY_SHA256SUMS)",) \
		$(if $(strip $(HARMONY_SIGNATURE_CERTIFICATE_SHA256)),--signature-certificate-sha256 "$(HARMONY_SIGNATURE_CERTIFICATE_SHA256)",) \
		$(if $(strip $(HARMONY_HOST_COMMIT)),--host-commit "$(HARMONY_HOST_COMMIT)",) \
		$(if $(strip $(HARMONY_HOST_BUILD_SHA256)),--host-build-sha256 "$(HARMONY_HOST_BUILD_SHA256)",)

harmony-hap-readiness:
	@test -n "$(strip $(HARMONY_HAP_READINESS_DIR))" || (echo "error: set HARMONY_HAP_READINESS_DIR to a HarmonyOS HAP readiness evidence directory" >&2; exit 2)
	mkdir -p "$(HARMONY_HAP_READINESS_DIR)"
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 scripts/harmony_hap_readiness.py \
		--evidence-dir "$(HARMONY_HAP_READINESS_DIR)" \
		$(if $(strip $(HARMONY_HDC_TARGET)),--hdc-target "$(HARMONY_HDC_TARGET)",) \
		$(if $(strip $(HARMONY_HAP)),--hap "$(HARMONY_HAP)",) \
		$(if $(strip $(HARMONY_SHA256SUMS)),--sha256sums "$(HARMONY_SHA256SUMS)",) \
		$(if $(strip $(HARMONY_SIGNATURE_CERTIFICATE)),--signature-certificate "$(HARMONY_SIGNATURE_CERTIFICATE)",) \
		$(if $(strip $(HARMONY_SIGNATURE_CERTIFICATE_SHA256)),--signature-certificate-sha256 "$(HARMONY_SIGNATURE_CERTIFICATE_SHA256)",) \
		$(if $(strip $(HARMONY_HOST_COMMIT)),--host-commit "$(HARMONY_HOST_COMMIT)",) \
		$(if $(strip $(HARMONY_HOST_BUILD_SHA256)),--host-build-sha256 "$(HARMONY_HOST_BUILD_SHA256)",) \
		$(HARMONY_HAP_READINESS_FLAGS)

harmony-device-gate:
	@test -n "$(strip $(EVIDENCE_DIR))" || (echo "error: set EVIDENCE_DIR to a HarmonyOS device evidence directory" >&2; exit 2)
	PYTHONDONTWRITEBYTECODE=1 python3 scripts/harmony_device_gate.py --evidence-root "$(EVIDENCE_DIR)" "$(EVIDENCE_DIR)/harmony-device-gates.json"

harmony-secure-pairing-gate:
	@test -n "$(strip $(EVIDENCE_DIR))" || (echo "error: set EVIDENCE_DIR to a HarmonyOS secure-pairing evidence directory" >&2; exit 2)
	PYTHONDONTWRITEBYTECODE=1 python3 scripts/harmony_secure_pairing_gate.py "$(EVIDENCE_DIR)/harmony-secure-pairing.json"

harmony-host-interop-preflight:
	@test -n "$(strip $(EVIDENCE_DIR))" || (echo "error: set EVIDENCE_DIR to a HarmonyOS Host interop evidence directory" >&2; exit 2)
	PYTHONDONTWRITEBYTECODE=1 python3 scripts/harmony_host_interop_preflight.py \
		--evidence-dir "$(EVIDENCE_DIR)" \
		--run-id "$(HARMONY_HOST_INTEROP_RUN_ID)"

harmony-host-interop-gate:
	@test -n "$(strip $(EVIDENCE_DIR))" || (echo "error: set EVIDENCE_DIR to a HarmonyOS Host interop evidence directory" >&2; exit 2)
	@test -f "$(HARMONY_HOST_INTEROP_JSON)" || (echo "error: set HARMONY_HOST_INTEROP_JSON to a redacted HarmonyOS Host interop manifest" >&2; exit 2)
	PYTHONDONTWRITEBYTECODE=1 python3 scripts/harmony_host_interop_preflight.py \
		--evidence-root "$(EVIDENCE_DIR)" \
		"$(HARMONY_HOST_INTEROP_JSON)"

harmony-avcodec-preflight:
	@test -n "$(strip $(EVIDENCE_DIR))" || (echo "error: set EVIDENCE_DIR to a HarmonyOS AVCodec evidence directory" >&2; exit 2)
	mkdir -p "$(EVIDENCE_DIR)"
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.harmony_avcodec_preflight \
		--output "$(EVIDENCE_DIR)/harmony-avcodec-preflight.json" \
		$(if $(strip $(HARMONY_AVCODEC_HDC_TARGET)),--hdc-target "$(HARMONY_AVCODEC_HDC_TARGET)",) \
		$(if $(strip $(HARMONY_AVCODEC_HAP)),--hap "$(HARMONY_AVCODEC_HAP)",)

harmony-avcodec-validate:
	@test -n "$(strip $(EVIDENCE_DIR))" || (echo "error: set EVIDENCE_DIR to a HarmonyOS AVCodec evidence directory" >&2; exit 2)
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.harmony_avcodec_preflight \
		--evidence-root "$(EVIDENCE_DIR)" \
		--validate "$(EVIDENCE_DIR)/harmony-avcodec-preflight.json"

harmony-current-base-gate:
	@test -n "$(strip $(EVIDENCE_DIR))" || (echo "error: set EVIDENCE_DIR to a HarmonyOS current-base evidence directory" >&2; exit 2)
	mkdir -p "$(dir $(HARMONY_CURRENT_BASE_GATE_JSON))"
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.harmony_current_base_gate \
		--readiness "$(HARMONY_READINESS_JSON)" \
		--device-gates "$(HARMONY_DEVICE_GATES_JSON)" \
		--evidence-root "$(EVIDENCE_DIR)" \
		--output "$(HARMONY_CURRENT_BASE_GATE_JSON)"

harmony-matepad-acceptance:
	@test -n "$(strip $(EVIDENCE_DIR))" || (echo "error: set EVIDENCE_DIR to a HarmonyOS MatePad Mini acceptance evidence directory" >&2; exit 2)
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 scripts/harmony_matepad_acceptance.py \
		--evidence-dir "$(EVIDENCE_DIR)" \
		$(if $(strip $(HARMONY_MATEPAD_ACCEPTANCE_WRITE_BLOCKED)),--write-blocked,)

ios-device-acceptance-gate:
	@test -f "$(IOS_ACCEPTANCE_JSON)" || (echo "error: set IOS_ACCEPTANCE_JSON to a sanitized iOS acceptance.json" >&2; exit 2)
	mkdir -p "$(dir $(IOS_ACCEPTANCE_GATE_JSON))"
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.ios_device_acceptance_gate \
		--acceptance "$(IOS_ACCEPTANCE_JSON)" \
		--evidence-root "$$(dirname "$(IOS_ACCEPTANCE_JSON)")" \
		--output "$(IOS_ACCEPTANCE_GATE_JSON)"

ios-hdr-edr-gate:
	mkdir -p "$(dir $(IOS_HDR_EDR_GATE_JSON))"
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.ios_hdr_edr_gate \
		--observations "$(IOS_HDR_EDR_OBSERVATIONS_JSON)" \
		--evidence-root "$$(dirname "$(IOS_HDR_EDR_OBSERVATIONS_JSON)")" \
		--repo . \
		--output "$(IOS_HDR_EDR_GATE_JSON)"

ios-app-signing-readiness-gate:
	@test -f "$(IOS_APP_SIGNING_READINESS_JSON)" || (echo "error: set IOS_APP_SIGNING_READINESS_JSON to sanitized iOS app-signing readiness JSON" >&2; exit 2)
	mkdir -p "$(dir $(IOS_APP_SIGNING_READINESS_GATE_JSON))"
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.ios_app_signing_readiness \
		--readiness "$(IOS_APP_SIGNING_READINESS_JSON)" \
		--evidence-root "$$(dirname "$(IOS_APP_SIGNING_READINESS_JSON)")" \
		--output "$(IOS_APP_SIGNING_READINESS_GATE_JSON)"

ios-app-signing-current-base-gate: ios-app-signing-readiness-gate

define SOAK_RECIPE
	mkdir -p $(EVIDENCE_DIR)/$@
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.soak --serial $(EVIDENCE_SERIAL) --preset $(@:soak-%=%) --interval 30s --package $(EVIDENCE_PACKAGE) $(if $(strip $(HOST_PID)),--host-pid $(HOST_PID),$(if $(strip $(EVIDENCE_HOST_PID)),--host-pid $(EVIDENCE_HOST_PID),)) --telemetry-jsonl $(EVIDENCE_DIR)/$@/host-telemetry.jsonl --require-stream-telemetry --output-jsonl $(EVIDENCE_DIR)/$@/samples.jsonl --summary-json $(EVIDENCE_DIR)/$@/summary.json
endef

soak-30m soak-8h: require-evidence-serial
	$(SOAK_RECIPE)

soak-2h: require-evidence-serial require-host-pid
	$(SOAK_RECIPE)

host-rss-gate:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.soak_report --summary $(EVIDENCE_DIR)/soak-2h/summary.json --samples $(EVIDENCE_DIR)/soak-2h/samples.jsonl --host-telemetry $(EVIDENCE_DIR)/soak-2h/host-telemetry.jsonl --output $(EVIDENCE_DIR)/soak-2h/exact-window-report.json
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.host_rss_gate --summary $(EVIDENCE_DIR)/soak-2h/summary.json --samples $(EVIDENCE_DIR)/soak-2h/samples.jsonl --exact-window-report $(EVIDENCE_DIR)/soak-2h/exact-window-report.json --output $(EVIDENCE_DIR)/soak-2h/host-rss-gate.json

soak-2h-host-rss-gate: require-evidence-serial require-host-pid
	$(MAKE) soak-2h EVIDENCE_SERIAL="$(EVIDENCE_SERIAL)" EVIDENCE_DIR="$(EVIDENCE_DIR)" EVIDENCE_PACKAGE="$(EVIDENCE_PACKAGE)" HOST_PID="$(HOST_PID)" EVIDENCE_HOST_PID="$(EVIDENCE_HOST_PID)"
	$(MAKE) host-rss-gate EVIDENCE_DIR="$(EVIDENCE_DIR)"

phase2-tablet-manifest: require-evidence-serial
	@test -f "$(EVIDENCE_DIR)/device-info.json" || (echo "error: collect $(EVIDENCE_DIR)/device-info.json with make evidence-device-info before phase2-tablet-manifest" >&2; exit 2)
	@test -n "$(strip $(PHASE2_DEVICE_CLASS))" || (echo "error: set PHASE2_DEVICE_CLASS to physical_8_9_inch_tablet or android_substitute" >&2; exit 2)
	@test -n "$(strip $(PHASE2_STAND_SETUP))" || (echo "error: set PHASE2_STAND_SETUP" >&2; exit 2)
	@test -n "$(strip $(PHASE2_CHARGER))" || (echo "error: set PHASE2_CHARGER" >&2; exit 2)
	@test -n "$(strip $(PHASE2_CABLE_OR_DOCK))" || (echo "error: set PHASE2_CABLE_OR_DOCK" >&2; exit 2)
	@test -n "$(strip $(PHASE2_VIDEO_PREFERENCES))" || (echo "error: set PHASE2_VIDEO_PREFERENCES" >&2; exit 2)
	@test -n "$(strip $(PHASE2_HOST_IDENTITY))" || (echo "error: set PHASE2_HOST_IDENTITY" >&2; exit 2)
	@test -n "$(strip $(PHASE2_HOST_BUILD))" || (echo "error: set PHASE2_HOST_BUILD" >&2; exit 2)
	@test -n "$(strip $(PHASE2_APK_SHA256))" || (echo "error: set PHASE2_APK_SHA256" >&2; exit 2)
	@test -n "$(strip $(PHASE2_BATTERY_TEMPERATURE_LIMIT_CELSIUS))" || (echo "error: set PHASE2_BATTERY_TEMPERATURE_LIMIT_CELSIUS" >&2; exit 2)
	@test -n "$(strip $(PHASE2_MAXIMUM_NET_BATTERY_DRAIN_PERCENT))" || (echo "error: set PHASE2_MAXIMUM_NET_BATTERY_DRAIN_PERCENT" >&2; exit 2)
	@test -n "$(strip $(EVIDENCE_HOST_PID))" || (echo "error: set EVIDENCE_HOST_PID to the running Host process PID for Phase 2 device-memory evidence" >&2; exit 2)
	mkdir -p $(EVIDENCE_DIR)
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.phase2_tablet_manifest \
		--output $(EVIDENCE_DIR)/phase2-tablet-manifest.json \
		--device-info $(EVIDENCE_DIR)/device-info.json \
		--device-class $(PHASE2_DEVICE_CLASS) \
		$(if $(strip $(PHASE2_TABLET_SIZE_INCHES)),--tablet-size-inches "$(PHASE2_TABLET_SIZE_INCHES)",) \
		--stand-setup "$(PHASE2_STAND_SETUP)" \
		--charger "$(PHASE2_CHARGER)" \
		--cable-or-dock "$(PHASE2_CABLE_OR_DOCK)" \
		$(if $(strip $(PHASE2_AMBIENT_TEMPERATURE_CELSIUS)),--ambient-temperature-celsius $(PHASE2_AMBIENT_TEMPERATURE_CELSIUS),) \
		--transport $(PHASE2_TRANSPORT) \
		--video-preferences "$(PHASE2_VIDEO_PREFERENCES)" \
		--host-pid $(EVIDENCE_HOST_PID) \
		--host-rss-source "soak --host-pid sampling via ps -o rss=" \
		--android-pss-source "ADB dumpsys meminfo $(EVIDENCE_PACKAGE) TOTAL PSS" \
		--thermal-limit-status $(PHASE2_THERMAL_LIMIT_STATUS) \
		$(if $(strip $(PHASE2_BATTERY_TEMPERATURE_LIMIT_CELSIUS)),--battery-temperature-limit-celsius $(PHASE2_BATTERY_TEMPERATURE_LIMIT_CELSIUS),) \
		$(if $(strip $(PHASE2_MAXIMUM_NET_BATTERY_DRAIN_PERCENT)),--maximum-net-battery-drain-percent $(PHASE2_MAXIMUM_NET_BATTERY_DRAIN_PERCENT),) \
		$(if $(strip $(PHASE2_RECOVERY_SCENARIOS)),--recovery-scenarios "$(PHASE2_RECOVERY_SCENARIOS)",) \
		--host-identity "$(PHASE2_HOST_IDENTITY)" \
		--host-build "$(PHASE2_HOST_BUILD)" \
		--apk-sha256 "$(PHASE2_APK_SHA256)" \
		-- make soak-8h EVIDENCE_SERIAL=$(EVIDENCE_SERIAL) EVIDENCE_DIR=$(EVIDENCE_DIR) EVIDENCE_HOST_PID=$(EVIDENCE_HOST_PID)

phase2-tablet-soak-preflight phase2-tablet-soak-run: require-evidence-serial
	@test -n "$(strip $(PHASE2_DEVICE_CLASS))" || (echo "error: set PHASE2_DEVICE_CLASS to physical_8_9_inch_tablet or android_substitute" >&2; exit 2)
	@test -n "$(strip $(PHASE2_STAND_SETUP))" || (echo "error: set PHASE2_STAND_SETUP" >&2; exit 2)
	@test -n "$(strip $(PHASE2_CHARGER))" || (echo "error: set PHASE2_CHARGER" >&2; exit 2)
	@test -n "$(strip $(PHASE2_CABLE_OR_DOCK))" || (echo "error: set PHASE2_CABLE_OR_DOCK" >&2; exit 2)
	@test -n "$(strip $(PHASE2_VIDEO_PREFERENCES))" || (echo "error: set PHASE2_VIDEO_PREFERENCES" >&2; exit 2)
	@test -n "$(strip $(PHASE2_HOST_IDENTITY))" || (echo "error: set PHASE2_HOST_IDENTITY" >&2; exit 2)
	@test -n "$(strip $(PHASE2_HOST_BUILD))" || (echo "error: set PHASE2_HOST_BUILD" >&2; exit 2)
	@if [ "$@" = "phase2-tablet-soak-run" ]; then test -n "$(strip $(PHASE2_APK_PATH)$(PHASE2_APK_SHA256))" || (echo "error: set PHASE2_APK_PATH or PHASE2_APK_SHA256" >&2; exit 2); fi
	mkdir -p $(EVIDENCE_DIR)
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.phase2_tablet_soak \
		--serial $(EVIDENCE_SERIAL) \
		--output-dir $(EVIDENCE_DIR) \
		--mode $(@:phase2-tablet-soak-%=%) \
		--package $(EVIDENCE_PACKAGE) \
		$(if $(strip $(PHASE2_HOST_PID)),--host-pid $(PHASE2_HOST_PID),) \
		$(if $(strip $(PHASE2_HOST_TELEMETRY_JSONL)),--host-telemetry-jsonl "$(PHASE2_HOST_TELEMETRY_JSONL)",) \
		$(if $(strip $(PHASE2_HOST_LOG)),--host-log "$(PHASE2_HOST_LOG)",) \
		$(if $(strip $(PHASE2_APK_PATH)),--apk "$(PHASE2_APK_PATH)",$(if $(strip $(PHASE2_APK_SHA256)),--apk-sha256 "$(PHASE2_APK_SHA256)",)) \
		--device-class $(PHASE2_DEVICE_CLASS) \
		$(if $(strip $(PHASE2_TABLET_SIZE_INCHES)),--tablet-size-inches "$(PHASE2_TABLET_SIZE_INCHES)",) \
		--stand-setup "$(PHASE2_STAND_SETUP)" \
		--charger "$(PHASE2_CHARGER)" \
		--cable-or-dock "$(PHASE2_CABLE_OR_DOCK)" \
		$(if $(strip $(PHASE2_AMBIENT_TEMPERATURE_CELSIUS)),--ambient-temperature-celsius $(PHASE2_AMBIENT_TEMPERATURE_CELSIUS),) \
		--transport $(PHASE2_TRANSPORT) \
		--video-preferences "$(PHASE2_VIDEO_PREFERENCES)" \
		--host-identity "$(PHASE2_HOST_IDENTITY)" \
		--host-build "$(PHASE2_HOST_BUILD)" \
		--gate-owners "$(PHASE2_GATE_OWNERS)" \
		--duration $(PHASE2_SOAK_DURATION) \
		--preflight-duration $(PHASE2_SOAK_PREFLIGHT_DURATION) \
		--interval $(PHASE2_SOAK_INTERVAL) \
		--thermal-limit-status $(PHASE2_THERMAL_LIMIT_STATUS) \
		$(if $(strip $(PHASE2_BATTERY_TEMPERATURE_LIMIT_CELSIUS)),--battery-temperature-limit-celsius $(PHASE2_BATTERY_TEMPERATURE_LIMIT_CELSIUS),) \
		$(if $(strip $(PHASE2_MAXIMUM_NET_BATTERY_DRAIN_PERCENT)),--maximum-net-battery-drain-percent $(PHASE2_MAXIMUM_NET_BATTERY_DRAIN_PERCENT),) \
		$(if $(strip $(PHASE2_RECOVERY_SCENARIOS)),--recovery-scenarios "$(PHASE2_RECOVERY_SCENARIOS)",)

phase2-device-memory-gate:
	@test -f "$(EVIDENCE_DIR)/phase2-tablet-manifest.json" || (echo "error: create $(EVIDENCE_DIR)/phase2-tablet-manifest.json before phase2-device-memory-gate" >&2; exit 2)
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.soak_report --summary $(EVIDENCE_DIR)/soak-8h/summary.json --samples $(EVIDENCE_DIR)/soak-8h/samples.jsonl --host-telemetry $(EVIDENCE_DIR)/soak-8h/host-telemetry.jsonl --output $(EVIDENCE_DIR)/soak-8h/exact-window-report.json
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.phase2_device_memory_gate --manifest $(EVIDENCE_DIR)/phase2-tablet-manifest.json --report $(EVIDENCE_DIR)/soak-8h/exact-window-report.json --output $(EVIDENCE_DIR)/soak-8h/phase2-device-memory-gate.json

phase2-device-environment-summary:
	@rm -f "$(EVIDENCE_DIR)/soak-8h/phase2-device-environment-summary.json"
	@set +e; \
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.phase2_device_environment $(EVIDENCE_DIR)/phase2-device-environment-observations.json --evidence-dir $(EVIDENCE_DIR) --output $(EVIDENCE_DIR)/soak-8h/phase2-device-environment-summary.json >/dev/null; \
	status=$$?; \
	if [ ! -f "$(EVIDENCE_DIR)/soak-8h/phase2-device-environment-summary.json" ]; then \
		test $$status -ne 0 && exit $$status || exit 1; \
	fi; \
	exit 0

phase2-device-environment-gate: phase2-device-environment-summary
	@PYTHONDONTWRITEBYTECODE=1 python3 -c 'import json, sys; summary = json.load(open(sys.argv[1], encoding="utf-8")); print(json.dumps(summary, sort_keys=True)); sys.exit(0 if summary.get("verdict") == "pass" else 1)' "$(EVIDENCE_DIR)/soak-8h/phase2-device-environment-summary.json"

phase2-tablet-gate: phase2-device-memory-gate
	$(MAKE) phase2-device-environment-summary EVIDENCE_DIR="$(EVIDENCE_DIR)"
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.phase2_tablet_gate --report $(EVIDENCE_DIR)/soak-8h/exact-window-report.json --manifest $(EVIDENCE_DIR)/phase2-tablet-manifest.json --evidence-dir $(EVIDENCE_DIR) --output $(EVIDENCE_DIR)/soak-8h/phase2-tablet-gate.json

hardware-keyboard-gate:
	@test -f "$(EVIDENCE_DIR)/hardware-keyboard-observations.json" || (echo "error: collect $(EVIDENCE_DIR)/hardware-keyboard-observations.json before hardware-keyboard-gate" >&2; exit 2)
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.hardware_keyboard $(EVIDENCE_DIR)/hardware-keyboard-observations.json --output $(EVIDENCE_DIR)/hardware-keyboard-summary.json --require-pass

ios-native-input-gate:
	@test -f "$(IOS_NATIVE_INPUT_OBSERVATIONS_JSON)" || (echo "error: set IOS_NATIVE_INPUT_OBSERVATIONS_JSON to sanitized iOS native-input observations JSON" >&2; exit 2)
	mkdir -p "$(dir $(IOS_NATIVE_INPUT_GATE_JSON))"
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.ios_native_input $(IOS_NATIVE_INPUT_OBSERVATIONS_JSON) --repo . --output $(IOS_NATIVE_INPUT_GATE_JSON) --require-pass

hardware-keyboard-readiness: require-evidence-serial
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 scripts/hardware_keyboard_readiness.py \
		--serial "$(EVIDENCE_SERIAL)" \
		--evidence-dir "$(EVIDENCE_DIR)" \
		--package "$(EVIDENCE_PACKAGE)" \
		--port "$(EVIDENCE_PORT)" \
		--write-blocked-on-lock

ios-current-base-manifest:
	mkdir -p $(EVIDENCE_DIR)
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.ios_current_base_manifest \
		--output $(EVIDENCE_DIR)/ios-current-base-manifest.json \
		--signing-readiness-gate "$(IOS_APP_SIGNING_READINESS_GATE_JSON)" \
		--native-input-gate "$(IOS_NATIVE_INPUT_GATE_JSON)" \
		-- make ios-current-base-gate EVIDENCE_DIR=$(EVIDENCE_DIR)

ios-current-base-gate:
	@test -f "$(EVIDENCE_DIR)/ios-current-base-manifest.json" || $(MAKE) ios-current-base-manifest EVIDENCE_DIR="$(EVIDENCE_DIR)"
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.ios_current_base_gate \
		--manifest $(EVIDENCE_DIR)/ios-current-base-manifest.json \
		--output $(EVIDENCE_DIR)/ios-current-base-gate.json

phase5-multi-client-current-base-gate:
	@mkdir -p "$(dir $(PHASE5_MULTI_CLIENT_GATE_JSON))"
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.phase5_multi_client_current_base_gate \
		--evidence-dir "$(EVIDENCE_DIR)" \
		--output "$(PHASE5_MULTI_CLIENT_GATE_JSON)"

clipboard-e2e-gate:
	@mkdir -p "$(dir $(CLIPBOARD_E2E_GATE_JSON))"
	@set +e; \
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.clipboard_e2e_gate \
		--host-readiness "$(CLIPBOARD_E2E_HOST_READINESS_JSON)" \
		--usb-preflight "$(CLIPBOARD_E2E_USB_PREFLIGHT_JSON)" \
		--trusted-lan-preflight "$(CLIPBOARD_E2E_LAN_PREFLIGHT_JSON)" \
		--android-clipboard-instrumentation-log "$(CLIPBOARD_E2E_ANDROID_INSTRUMENTATION_LOG)" \
		--product-e2e "$(CLIPBOARD_E2E_PRODUCT_JSON)" \
		--serial-label "REDACTED_P0110_USB_SERIAL" \
		--output "$(CLIPBOARD_E2E_GATE_JSON)" \
		$(if $(filter 1 true yes,$(CLIPBOARD_E2E_REQUIRE_PASS)),--require-pass,); \
	status=$$?; \
	if [ $$status -ne 0 ]; then \
		if [ -z "$(filter 1 true yes,$(CLIPBOARD_E2E_REQUIRE_PASS))" ] && [ $$status -eq 2 ]; then exit 0; fi; \
		exit $$status; \
	fi

file-transfer-android-smoke:
	@mkdir -p "$(dir $(FILE_TRANSFER_ANDROID_SMOKE_GATE_JSON))"
	@set +e; \
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.file_transfer_android_smoke \
		--host-readiness "$(FILE_TRANSFER_ANDROID_SMOKE_HOST_READINESS_JSON)" \
		--usb-preflight "$(FILE_TRANSFER_ANDROID_SMOKE_USB_PREFLIGHT_JSON)" \
		--trusted-lan-preflight "$(FILE_TRANSFER_ANDROID_SMOKE_LAN_PREFLIGHT_JSON)" \
		--android-file-transfer-instrumentation-log "$(FILE_TRANSFER_ANDROID_SMOKE_ANDROID_INSTRUMENTATION_LOG)" \
		--product-e2e "$(FILE_TRANSFER_ANDROID_SMOKE_PRODUCT_JSON)" \
		--serial-label "REDACTED_P0110_USB_SERIAL" \
		--output "$(FILE_TRANSFER_ANDROID_SMOKE_GATE_JSON)" \
		$(if $(filter 1 true yes,$(FILE_TRANSFER_ANDROID_SMOKE_REQUIRE_PASS)),--require-pass,); \
	status=$$?; \
	if [ $$status -ne 0 ]; then \
		if [ -z "$(strip $(FILE_TRANSFER_ANDROID_SMOKE_REQUIRE_PASS))" ] && [ $$status -eq 2 ]; then exit 0; fi; \
		exit $$status; \
	fi

host-display-rotation-gate:
	@test -f "$(EVIDENCE_DIR)/host-display-rotation.json" || (echo "error: collect $(EVIDENCE_DIR)/host-display-rotation.json first" >&2; exit 2)
	@PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.host_display_rotation_gate "$(EVIDENCE_DIR)/host-display-rotation.json" --check-artifacts --output "$(EVIDENCE_DIR)/host-display-rotation-gate.json"

host-display-rotation-current-base-manifest:
	@mkdir -p $(EVIDENCE_DIR)
	@PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.host_display_rotation_current_base_manifest --output $(EVIDENCE_DIR)/host-display-rotation-current-base-manifest.json $(if $(strip $(EVIDENCE_SERIAL)),--adb-serial $(EVIDENCE_SERIAL),) -- make host-display-rotation-current-base-gate EVIDENCE_DIR=$(EVIDENCE_DIR) $(if $(strip $(EVIDENCE_SERIAL)),EVIDENCE_SERIAL=$(EVIDENCE_SERIAL),)

host-display-rotation-current-base-gate:
	@test -f "$(EVIDENCE_DIR)/host-display-rotation-current-base-manifest.json" || $(MAKE) host-display-rotation-current-base-manifest EVIDENCE_DIR="$(EVIDENCE_DIR)" EVIDENCE_SERIAL="$(EVIDENCE_SERIAL)"
	@PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.host_display_rotation_current_base_gate --manifest $(EVIDENCE_DIR)/host-display-rotation-current-base-manifest.json --output $(EVIDENCE_DIR)/host-display-rotation-current-base-gate.json

wake-host-current-base-gate:
	mkdir -p "$(EVIDENCE_DIR)"
	@test -f "$(WAKE_HOST_CURRENT_BASE_JSON)" || printf '%s\n' '{"blocking_notes": ["No explicit WakeHost current-base evidence was supplied."], "notes": "Default current-base WakeHost summary is intentionally empty and blocked until retained hardware WOL evidence is attached."}' > "$(WAKE_HOST_CURRENT_BASE_JSON)"
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.wake_host_current_base \
		"$(WAKE_HOST_CURRENT_BASE_JSON)" \
		--output "$(WAKE_HOST_CURRENT_BASE_GATE_JSON)"

phase2-tablet-preflight:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.phase2_tablet_preflight --evidence-dir $(EVIDENCE_DIR) --output $(EVIDENCE_DIR)/phase2-tablet-preflight.json

phase2-macos-startup-recovery-gate:
	@test -f "$(EVIDENCE_DIR)/macos-startup-recovery-evidence.json" || (echo "error: collect $(EVIDENCE_DIR)/macos-startup-recovery-evidence.json before phase2-macos-startup-recovery-gate" >&2; exit 2)
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.macos_startup_recovery_gate --evidence $(EVIDENCE_DIR)/macos-startup-recovery-evidence.json --output $(EVIDENCE_DIR)/macos-startup-recovery-gate.json

phase2-aggregate-owner:
	mkdir -p $(EVIDENCE_DIR)
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.phase2_aggregate_owner \
		--output $(EVIDENCE_DIR)/phase2-aggregate-owner.json \
		$(if $(strip $(PHASE2_TABLET_GATE)),--tablet-gate $(PHASE2_TABLET_GATE),) \
		$(if $(strip $(PHASE2_TABLET_MANIFEST)),--tablet-manifest $(PHASE2_TABLET_MANIFEST),) \
		$(if $(strip $(PHASE2_HARDWARE_KEYBOARD)),--hardware-keyboard $(PHASE2_HARDWARE_KEYBOARD),) \
		$(if $(strip $(PHASE2_DEVICE_MEMORY)),--device-memory $(PHASE2_DEVICE_MEMORY),) \
		$(if $(strip $(PHASE2_DEVICE_ENVIRONMENT)),--device-environment $(PHASE2_DEVICE_ENVIRONMENT),) \
		$(if $(strip $(PHASE2_SOAK_READINESS)),--soak-readiness $(PHASE2_SOAK_READINESS),) \
		$(if $(strip $(PHASE2_TABLET_UI)),--tablet-ui $(PHASE2_TABLET_UI),) \
		$(if $(strip $(PHASE2_RECOVERY)),--recovery $(PHASE2_RECOVERY),) \
		$(if $(strip $(PHASE2_LOGIN_HEADLESS)),--login-headless $(PHASE2_LOGIN_HEADLESS),)

macos-hardware-compatibility-gate:
	@test -f "$(EVIDENCE_DIR)/macos-hardware-compatibility.json" || (echo "error: collect $(EVIDENCE_DIR)/macos-hardware-compatibility.json before macos-hardware-compatibility-gate" >&2; exit 2)
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.macos_hardware_compatibility "$(EVIDENCE_DIR)/macos-hardware-compatibility.json" --evidence-dir "$(EVIDENCE_DIR)" --output "$(EVIDENCE_DIR)/macos-hardware-compatibility-gate.json"
