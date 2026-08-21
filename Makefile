BUF_VERSION ?= v1.72.0
BUF := go run github.com/bufbuild/buf/cmd/buf@$(BUF_VERSION)
EVIDENCE_SERIAL ?=
EVIDENCE_DIR ?= .build/evidence
EVIDENCE_PACKAGE ?= dev.telemachus.display
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
PHASE2_APK_SHA256 ?=
PHASE2_RECOVERY_SCENARIOS ?=
PHASE2_THERMAL_LIMIT_STATUS ?= 2
PHASE2_BATTERY_TEMPERATURE_LIMIT_CELSIUS ?=
PHASE2_MAXIMUM_NET_BATTERY_DRAIN_PERCENT ?=
TOUCH_RERUN_EXPECTED_HOST_SHA256 ?=
PHASE3_LOCAL_SYNTHETIC_E2E_DIR ?= .build/phase3-local-synthetic-product-e2e
PHASE3_LOCAL_SYNTHETIC_E2E_PUBLIC_DIR ?= $(PHASE3_LOCAL_SYNTHETIC_E2E_DIR)/public
PHASE3_LOCAL_SYNTHETIC_E2E_TIMEOUT_SECONDS ?= 90
PHASE3_PUBLIC_INTERNET_EVIDENCE_DIR ?= .build/phase3-public-internet
PHASE3_PUBLIC_INTERNET_ALLOW_BLOCKED ?=
PHASE3_PUBLIC_INTERNET_RELAY_CONFIG ?= deploy/phase3/config/relay.production.json
PHASE3_PUBLIC_INTERNET_COTURN_CONFIG ?= deploy/phase3/coturn/production.conf
PHASE3_PUBLIC_INTERNET_TURN_SECRET_FILE ?= deploy/phase3/secrets/turn_secret.txt
PHASE3_PUBLIC_INTERNET_TLS_CERTIFICATE ?= deploy/phase3/tls/fullchain.pem
PHASE3_PUBLIC_INTERNET_TLS_PRIVATE_KEY ?= deploy/phase3/tls/privkey.pem
PHASE3_PUBLIC_INTERNET_COTURN_EXTERNAL_IP ?=
PHASE3_PUBLIC_INTERNET_TURN_REALM ?=
PHASE3_PUBLIC_INTERNET_TURN_URI ?=
PHASE3_PUBLIC_INTERNET_TURN_URIS ?= $(PHASE3_PUBLIC_INTERNET_TURN_URI)
PHASE3_PUBLIC_INTERNET_AUTHORITY_SOURCE_ID ?=
PHASE3_PUBLIC_INTERNET_AUTHORITY_READY_URL ?=
PHASE3_PUBLIC_INTERNET_RELAY_READY_URL ?=
PHASE3_PUBLIC_INTERNET_RELAY_URL ?=
PHASE3_PUBLIC_INTERNET_SIGNALING_ORIGIN ?=
PHASE3_PUBLIC_INTERNET_RELAY_ORIGIN ?=
PHASE3_PUBLIC_INTERNET_CLIENT_TOKEN_FILE ?= deploy/phase3/secrets/client_token.txt
PHASE3_PUBLIC_INTERNET_DEVICE_ID ?=
PHASE3_PUBLIC_INTERNET_SESSION_ID ?=
PHASE3_PUBLIC_INTERNET_ALLOCATION_ID ?=
PHASE3_PUBLIC_INTERNET_PEER_HOST ?=
PHASE3_PUBLIC_INTERNET_PEER_PORT ?=
PHASE3_PUBLIC_INTERNET_PRIVATE_SOAK_SUMMARY ?=
PHASE3_PUBLIC_INTERNET_PLANNED_HANDOFFS ?=
PHASE3_TURNSERVER ?= $(shell command -v turnserver 2>/dev/null)
PHASE3_WEBRTC_E2E_SCHEMA := dev.vibescreen.phase3-webrtc-e2e/v1
PHASE3_COTURN_COMPATIBLE_VERSIONS := 4.15.0 4.16.0 4.17.0

.PHONY: protocol protocol-tests phase3-test phase3-go-test phase3-authority-container-test phase3-local-synthetic-product-e2e phase3-local-synthetic-public-artifacts-check phase3-local-product-e2e phase3-public-internet-preflight phase3-remote-turn-verifier phase3-internet-manifest phase3-internet-soak baseline-macos-build baseline-macos-test baseline-macos-self-test baseline-macos-app baseline-macos-dev-install baseline-macos-touch-preflight baseline-android-test baseline-android-transport-boundary baseline-android-check baseline-android-apk baseline-android-dependency-audit evidence-tools-test release-tools-test require-evidence-serial evidence-device-info evidence-touch-rerun-preflight harmony-device-gate soak-30m soak-2h soak-8h phase2-tablet-manifest phase2-tablet-gate

protocol:
	cd contracts && $(BUF) format --diff --exit-code
	cd contracts && $(BUF) lint
	cd contracts && $(BUF) build
	cd contracts && $(BUF) breaking --against fixtures/v1.binpb
	$(MAKE) protocol-tests

protocol-tests:
	PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s contracts/tests -p 'test_*.py' -v

phase3-test: phase3-go-test
	PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/phase3 -p 'test_*.py' -v
	PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/phase3_webrtc -p 'test_*.py' -v
	PYTHONDONTWRITEBYTECODE=1 python3 scripts/phase3/evidence_privacy.py --evidence-dir docs/changes/2026-08-04-phase-3-secure-internet/evidence/2026-08-05-nubia-p0110-internet --check

phase3-go-test:
	cd packages/security && test -z "$$(gofmt -l .)" && go vet ./... && go test -race -count=1 ./...
	$(MAKE) -C services/signaling verify
	$(MAKE) -C services/relay verify
	$(MAKE) -C services/authority verify

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
	@jq -e 'select(.schema == "$(PHASE3_WEBRTC_E2E_SCHEMA)" and .result == "pass" and .mode == "direct" and .slice == "product" and .signaling.real_process == true and .webrtc.selected_route == "direct" and (.webrtc.selected_candidate_pair | startswith("direct(")) and .product_session.host == "InternetProductSession" and .product_session.device == "synthetic Protocol v1 harness" and .product_session.capture_or_stream_server_started == false)' "$(PHASE3_LOCAL_SYNTHETIC_E2E_DIR)/direct.json" >/dev/null
	PYTHONDONTWRITEBYTECODE=1 python3 scripts/phase3_webrtc/run_local_e2e.py --mode relay --slice product --skip-build --turnserver "$(PHASE3_TURNSERVER)" --timeout-seconds "$(PHASE3_LOCAL_SYNTHETIC_E2E_TIMEOUT_SECONDS)" --diagnostics-dir "$(PHASE3_LOCAL_SYNTHETIC_E2E_DIR)/relay-logs" --output "$(PHASE3_LOCAL_SYNTHETIC_E2E_DIR)/relay.json"
	@jq -e 'select(.schema == "$(PHASE3_WEBRTC_E2E_SCHEMA)" and .result == "pass" and .mode == "relay" and .slice == "product" and .signaling.real_process == true and .webrtc.selected_route == "relay" and (.webrtc.selected_candidate_pair | startswith("relay(")) and .coturn.real_process == true and .coturn.forced_libwebrtc_relay == "pass" and .product_session.host == "InternetProductSession" and .product_session.device == "synthetic Protocol v1 harness" and .product_session.capture_or_stream_server_started == false)' "$(PHASE3_LOCAL_SYNTHETIC_E2E_DIR)/relay.json" >/dev/null
	$(MAKE) phase3-local-synthetic-public-artifacts-check

phase3-local-synthetic-public-artifacts-check:
	PYTHONDONTWRITEBYTECODE=1 python3 scripts/phase3_webrtc/public_artifacts.py --root "$(PHASE3_LOCAL_SYNTHETIC_E2E_DIR)" --output "$(PHASE3_LOCAL_SYNTHETIC_E2E_PUBLIC_DIR)"

phase3-local-product-e2e:
	@printf '%s\n' 'warning: phase3-local-product-e2e is deprecated; use phase3-local-synthetic-product-e2e (synthetic Protocol v1 harness only; no Android device or ScreenCaptureKit capture).' >&2
	@$(MAKE) phase3-local-synthetic-product-e2e

phase3-public-internet-preflight:
	mkdir -p "$(PHASE3_PUBLIC_INTERNET_EVIDENCE_DIR)"
	PYTHONDONTWRITEBYTECODE=1 python3 scripts/phase3/remote_turn_preflight.py \
		--relay-config "$(PHASE3_PUBLIC_INTERNET_RELAY_CONFIG)" \
		--coturn-config "$(PHASE3_PUBLIC_INTERNET_COTURN_CONFIG)" \
		--turn-secret-file "$(PHASE3_PUBLIC_INTERNET_TURN_SECRET_FILE)" \
		--tls-certificate "$(PHASE3_PUBLIC_INTERNET_TLS_CERTIFICATE)" \
		--tls-private-key "$(PHASE3_PUBLIC_INTERNET_TLS_PRIVATE_KEY)" \
		$(if $(strip $(PHASE3_PUBLIC_INTERNET_COTURN_EXTERNAL_IP)),--coturn-external-ip "$(PHASE3_PUBLIC_INTERNET_COTURN_EXTERNAL_IP)",) \
		$(if $(strip $(PHASE3_PUBLIC_INTERNET_AUTHORITY_READY_URL)),--authority-ready-url "$(PHASE3_PUBLIC_INTERNET_AUTHORITY_READY_URL)",) \
		$(if $(strip $(PHASE3_PUBLIC_INTERNET_RELAY_READY_URL)),--relay-ready-url "$(PHASE3_PUBLIC_INTERNET_RELAY_READY_URL)",) \
		$(if $(strip $(PHASE3_PUBLIC_INTERNET_ALLOW_BLOCKED)),--allow-blocked,) \
		--output "$(PHASE3_PUBLIC_INTERNET_EVIDENCE_DIR)/preflight.json"

phase3-remote-turn-verifier: phase3-public-internet-preflight
	@test -n "$(strip $(PHASE3_PUBLIC_INTERNET_RELAY_URL))" || (echo "error: set PHASE3_PUBLIC_INTERNET_RELAY_URL" >&2; exit 2)
	@test -n "$(strip $(PHASE3_PUBLIC_INTERNET_DEVICE_ID))" || (echo "error: set PHASE3_PUBLIC_INTERNET_DEVICE_ID" >&2; exit 2)
	@test -n "$(strip $(PHASE3_PUBLIC_INTERNET_SESSION_ID))" || (echo "error: set PHASE3_PUBLIC_INTERNET_SESSION_ID" >&2; exit 2)
	@test -n "$(strip $(PHASE3_PUBLIC_INTERNET_ALLOCATION_ID))" || (echo "error: set PHASE3_PUBLIC_INTERNET_ALLOCATION_ID" >&2; exit 2)
	@test -n "$(strip $(PHASE3_PUBLIC_INTERNET_PEER_HOST))" || (echo "error: set PHASE3_PUBLIC_INTERNET_PEER_HOST" >&2; exit 2)
	@test -n "$(strip $(PHASE3_PUBLIC_INTERNET_PEER_PORT))" || (echo "error: set PHASE3_PUBLIC_INTERNET_PEER_PORT" >&2; exit 2)
	PYTHONDONTWRITEBYTECODE=1 python3 scripts/phase3/remote_turn_verifier.py \
		--preflight "$(PHASE3_PUBLIC_INTERNET_EVIDENCE_DIR)/preflight.json" \
		--relay-url "$(PHASE3_PUBLIC_INTERNET_RELAY_URL)" \
		--client-token-file "$(PHASE3_PUBLIC_INTERNET_CLIENT_TOKEN_FILE)" \
		--device-id "$(PHASE3_PUBLIC_INTERNET_DEVICE_ID)" \
		--session-id "$(PHASE3_PUBLIC_INTERNET_SESSION_ID)" \
		--allocation-id "$(PHASE3_PUBLIC_INTERNET_ALLOCATION_ID)" \
		--peer-host "$(PHASE3_PUBLIC_INTERNET_PEER_HOST)" \
		--peer-port "$(PHASE3_PUBLIC_INTERNET_PEER_PORT)" \
		--output "$(PHASE3_PUBLIC_INTERNET_EVIDENCE_DIR)/remote-turn-verifier.json"

phase3-internet-manifest:
	@test -n "$(strip $(PHASE3_PUBLIC_INTERNET_TURN_REALM))" || (echo "error: set PHASE3_PUBLIC_INTERNET_TURN_REALM" >&2; exit 2)
	@test -n "$(strip $(PHASE3_PUBLIC_INTERNET_TURN_URIS))" || (echo "error: set PHASE3_PUBLIC_INTERNET_TURN_URIS" >&2; exit 2)
	@test -n "$(strip $(PHASE3_PUBLIC_INTERNET_AUTHORITY_SOURCE_ID))" || (echo "error: set PHASE3_PUBLIC_INTERNET_AUTHORITY_SOURCE_ID" >&2; exit 2)
	@test -n "$(strip $(PHASE3_PUBLIC_INTERNET_SIGNALING_ORIGIN))" || (echo "error: set PHASE3_PUBLIC_INTERNET_SIGNALING_ORIGIN" >&2; exit 2)
	@test -n "$(strip $(PHASE3_PUBLIC_INTERNET_RELAY_ORIGIN))" || (echo "error: set PHASE3_PUBLIC_INTERNET_RELAY_ORIGIN" >&2; exit 2)
	@test -n "$(strip $(PHASE3_PUBLIC_INTERNET_PLANNED_HANDOFFS))" || (echo "error: set PHASE3_PUBLIC_INTERNET_PLANNED_HANDOFFS" >&2; exit 2)
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.phase3_internet_manifest \
		--output "$(PHASE3_PUBLIC_INTERNET_EVIDENCE_DIR)/phase3-internet-manifest.json" \
		--repo . \
		--turn-realm "$(PHASE3_PUBLIC_INTERNET_TURN_REALM)" \
		$(foreach uri,$(PHASE3_PUBLIC_INTERNET_TURN_URIS),--turn-uri "$(uri)" ) \
		--authority-source-id "$(PHASE3_PUBLIC_INTERNET_AUTHORITY_SOURCE_ID)" \
		--tls-certificate "$(PHASE3_PUBLIC_INTERNET_TLS_CERTIFICATE)" \
		--signaling-origin "$(PHASE3_PUBLIC_INTERNET_SIGNALING_ORIGIN)" \
		--relay-origin "$(PHASE3_PUBLIC_INTERNET_RELAY_ORIGIN)" \
		--planned-network-handoffs "$(PHASE3_PUBLIC_INTERNET_PLANNED_HANDOFFS)" \
		-- make phase3-internet-soak

phase3-internet-soak:
	mkdir -p "$(PHASE3_PUBLIC_INTERNET_EVIDENCE_DIR)"
	PYTHONDONTWRITEBYTECODE=1 python3 scripts/phase3/internet_soak.py \
		$(if $(wildcard $(PHASE3_PUBLIC_INTERNET_EVIDENCE_DIR)/preflight.json),--preflight "$(PHASE3_PUBLIC_INTERNET_EVIDENCE_DIR)/preflight.json",) \
		$(if $(wildcard $(PHASE3_PUBLIC_INTERNET_EVIDENCE_DIR)/remote-turn-verifier.json),--verifier "$(PHASE3_PUBLIC_INTERNET_EVIDENCE_DIR)/remote-turn-verifier.json",) \
		$(if $(strip $(PHASE3_PUBLIC_INTERNET_PRIVATE_SOAK_SUMMARY)),--private-summary "$(PHASE3_PUBLIC_INTERNET_PRIVATE_SOAK_SUMMARY)",) \
		$(if $(strip $(PHASE3_PUBLIC_INTERNET_ALLOW_BLOCKED)),--allow-blocked,) \
		--output "$(PHASE3_PUBLIC_INTERNET_EVIDENCE_DIR)/soak-summary.json"

baseline-macos-build:
	cd baseline/MacHost && swift build -c release

baseline-macos-test:
	cd baseline/MacHost && swift test

baseline-macos-self-test: baseline-macos-build
	"baseline/MacHost/.build/release/Vibe Screen" --host-self-test
	"baseline/MacHost/.build/release/Vibe Screen" --transport-self-test
	"baseline/MacHost/.build/release/Vibe Screen" --reliability-self-test
	"baseline/MacHost/.build/release/Vibe Screen" --protocol-v1-self-test
	"baseline/MacHost/.build/release/Vibe Screen" --video-encoder-self-test

baseline-macos-app:
	python3 scripts/package_macos.py

baseline-macos-dev-install:
	python3 scripts/macos_dev_host.py install

baseline-macos-touch-preflight:
	python3 scripts/macos_dev_host.py preflight

baseline-android-test:
	cd baseline/AndroidClient && ./gradlew :transport:check testDebugUnitTest

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

require-evidence-serial:
	@test -n "$(strip $(EVIDENCE_SERIAL))" || (echo "error: set EVIDENCE_SERIAL explicitly" >&2; exit 2)

evidence-device-info: require-evidence-serial
	mkdir -p $(EVIDENCE_DIR)
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.device_info --serial $(EVIDENCE_SERIAL) --package $(EVIDENCE_PACKAGE) --output $(EVIDENCE_DIR)/device-info.json

evidence-touch-rerun-preflight: require-evidence-serial
	mkdir -p $(EVIDENCE_DIR)
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools \
		python3 -m vibescreen_evidence.touch_rerun_preflight \
		--serial $(EVIDENCE_SERIAL) \
		$(if $(strip $(TOUCH_RERUN_EXPECTED_HOST_SHA256)),--expected-host-sha256 $(TOUCH_RERUN_EXPECTED_HOST_SHA256),) \
		--output $(EVIDENCE_DIR)/touch-rerun-preflight.json

harmony-device-gate:
	@test -n "$(strip $(EVIDENCE_DIR))" || (echo "error: set EVIDENCE_DIR to a HarmonyOS device evidence directory" >&2; exit 2)
	PYTHONDONTWRITEBYTECODE=1 python3 scripts/harmony_device_gate.py "$(EVIDENCE_DIR)/harmony-device-gates.json"

soak-30m soak-2h soak-8h: require-evidence-serial
	mkdir -p $(EVIDENCE_DIR)/$@
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.soak --serial $(EVIDENCE_SERIAL) --preset $(@:soak-%=%) --interval 30s --package $(EVIDENCE_PACKAGE) --telemetry-jsonl $(EVIDENCE_DIR)/$@/host-telemetry.jsonl --require-stream-telemetry --output-jsonl $(EVIDENCE_DIR)/$@/samples.jsonl --summary-json $(EVIDENCE_DIR)/$@/summary.json

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
		--thermal-limit-status $(PHASE2_THERMAL_LIMIT_STATUS) \
		$(if $(strip $(PHASE2_BATTERY_TEMPERATURE_LIMIT_CELSIUS)),--battery-temperature-limit-celsius $(PHASE2_BATTERY_TEMPERATURE_LIMIT_CELSIUS),) \
		$(if $(strip $(PHASE2_MAXIMUM_NET_BATTERY_DRAIN_PERCENT)),--maximum-net-battery-drain-percent $(PHASE2_MAXIMUM_NET_BATTERY_DRAIN_PERCENT),) \
		$(if $(strip $(PHASE2_RECOVERY_SCENARIOS)),--recovery-scenarios "$(PHASE2_RECOVERY_SCENARIOS)",) \
		--host-identity "$(PHASE2_HOST_IDENTITY)" \
		--host-build "$(PHASE2_HOST_BUILD)" \
		--apk-sha256 "$(PHASE2_APK_SHA256)" \
		-- make soak-8h EVIDENCE_SERIAL=$(EVIDENCE_SERIAL) EVIDENCE_DIR=$(EVIDENCE_DIR)

phase2-tablet-gate:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.soak_report --summary $(EVIDENCE_DIR)/soak-8h/summary.json --samples $(EVIDENCE_DIR)/soak-8h/samples.jsonl --host-telemetry $(EVIDENCE_DIR)/soak-8h/host-telemetry.jsonl --output $(EVIDENCE_DIR)/soak-8h/exact-window-report.json
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.phase2_tablet_gate --report $(EVIDENCE_DIR)/soak-8h/exact-window-report.json --output $(EVIDENCE_DIR)/soak-8h/phase2-tablet-gate.json
