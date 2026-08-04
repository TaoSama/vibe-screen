BUF_VERSION ?= v1.72.0
BUF := go run github.com/bufbuild/buf/cmd/buf@$(BUF_VERSION)
EVIDENCE_SERIAL ?= 100.72.246.116:5555
EVIDENCE_DIR ?= .build/evidence
EVIDENCE_PACKAGE ?= dev.telemachus.display

.PHONY: protocol baseline-macos-build baseline-macos-test baseline-macos-self-test baseline-macos-app baseline-android-test baseline-android-check baseline-android-apk baseline-android-dependency-audit evidence-tools-test evidence-device-info soak-30m soak-2h soak-8h

protocol:
	cd contracts && $(BUF) format --diff --exit-code
	cd contracts && $(BUF) lint
	cd contracts && $(BUF) build
	cd contracts && $(BUF) breaking --against fixtures/v1.binpb

baseline-macos-build:
	cd baseline/MacHost && swift build -c release

baseline-macos-test:
	cd baseline/MacHost && swift test

baseline-macos-self-test: baseline-macos-build
	baseline/MacHost/.build/release/Telemachus --host-self-test
	baseline/MacHost/.build/release/Telemachus --transport-self-test
	baseline/MacHost/.build/release/Telemachus --reliability-self-test

baseline-macos-app:
	python3 scripts/package_macos.py

baseline-android-test:
	cd baseline/AndroidClient && ./gradlew testDebugUnitTest

baseline-android-check:
	cd baseline/AndroidClient && ./gradlew testDebugUnitTest lintDebug assembleDebug auditReleaseDependencies

baseline-android-apk:
	cd baseline/AndroidClient && ./gradlew assembleDebug

baseline-android-dependency-audit:
	cd baseline/AndroidClient && ./gradlew auditReleaseDependencies

evidence-tools-test:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m unittest discover -s tools/tests -v

evidence-device-info:
	mkdir -p $(EVIDENCE_DIR)
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.device_info --serial $(EVIDENCE_SERIAL) --package $(EVIDENCE_PACKAGE) --output $(EVIDENCE_DIR)/device-info.json

soak-30m soak-2h soak-8h:
	mkdir -p $(EVIDENCE_DIR)/$@
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.soak --serial $(EVIDENCE_SERIAL) --preset $(@:soak-%=%) --interval 30s --package $(EVIDENCE_PACKAGE) --telemetry-jsonl $(EVIDENCE_DIR)/$@/host-telemetry.jsonl --require-stream-telemetry --output-jsonl $(EVIDENCE_DIR)/$@/samples.jsonl --summary-json $(EVIDENCE_DIR)/$@/summary.json
