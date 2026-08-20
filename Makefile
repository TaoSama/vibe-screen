BUF_VERSION ?= v1.72.0
BUF := go run github.com/bufbuild/buf/cmd/buf@$(BUF_VERSION)
EVIDENCE_SERIAL ?=
EVIDENCE_DIR ?= .build/evidence
EVIDENCE_PACKAGE ?= dev.telemachus.display
TOUCH_RERUN_EXPECTED_HOST_SHA256 ?=
PHASE3_LOCAL_SYNTHETIC_E2E_DIR ?= .build/phase3-local-synthetic-product-e2e
PHASE3_LOCAL_SYNTHETIC_E2E_PUBLIC_DIR ?= $(PHASE3_LOCAL_SYNTHETIC_E2E_DIR)/public
PHASE3_LOCAL_SYNTHETIC_E2E_TIMEOUT_SECONDS ?= 90
PHASE3_TURNSERVER ?= $(shell command -v turnserver 2>/dev/null)
PHASE3_WEBRTC_E2E_SCHEMA := dev.vibescreen.phase3-webrtc-e2e/v1
PHASE3_COTURN_COMPATIBLE_VERSIONS := 4.15.0 4.16.0 4.17.0

.PHONY: protocol protocol-tests phase3-test phase3-go-test phase3-authority-container-test phase3-local-synthetic-product-e2e phase3-local-synthetic-public-artifacts-check phase3-local-product-e2e baseline-macos-build baseline-macos-test baseline-macos-self-test baseline-macos-app baseline-macos-dev-install baseline-macos-touch-preflight baseline-android-test baseline-android-transport-boundary baseline-android-check baseline-android-apk baseline-android-dependency-audit evidence-tools-test release-tools-test require-evidence-serial evidence-device-info evidence-touch-rerun-preflight soak-30m soak-2h soak-8h phase2-tablet-gate

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

soak-30m soak-2h soak-8h: require-evidence-serial
	mkdir -p $(EVIDENCE_DIR)/$@
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.soak --serial $(EVIDENCE_SERIAL) --preset $(@:soak-%=%) --interval 30s --package $(EVIDENCE_PACKAGE) --telemetry-jsonl $(EVIDENCE_DIR)/$@/host-telemetry.jsonl --require-stream-telemetry --output-jsonl $(EVIDENCE_DIR)/$@/samples.jsonl --summary-json $(EVIDENCE_DIR)/$@/summary.json

phase2-tablet-gate:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.soak_report --summary $(EVIDENCE_DIR)/soak-8h/summary.json --samples $(EVIDENCE_DIR)/soak-8h/samples.jsonl --host-telemetry $(EVIDENCE_DIR)/soak-8h/host-telemetry.jsonl --output $(EVIDENCE_DIR)/soak-8h/exact-window-report.json
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.phase2_tablet_gate --report $(EVIDENCE_DIR)/soak-8h/exact-window-report.json --output $(EVIDENCE_DIR)/soak-8h/phase2-tablet-gate.json
