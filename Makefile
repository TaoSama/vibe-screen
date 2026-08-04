BUF_VERSION ?= v1.72.0
BUF := go run github.com/bufbuild/buf/cmd/buf@$(BUF_VERSION)
EVIDENCE_SERIAL ?=
EVIDENCE_DIR ?= .build/evidence
EVIDENCE_PACKAGE ?= dev.telemachus.display

.PHONY: protocol protocol-tests baseline-macos-build baseline-macos-test baseline-macos-self-test baseline-macos-app baseline-android-test baseline-android-check baseline-android-apk baseline-android-dependency-audit evidence-tools-test release-tools-test require-evidence-serial evidence-device-info soak-30m soak-2h soak-8h

protocol:
	cd contracts && $(BUF) format --diff --exit-code
	cd contracts && $(BUF) lint
	cd contracts && $(BUF) build
	cd contracts && $(BUF) breaking --against fixtures/v1.binpb
	$(MAKE) protocol-tests

protocol-tests:
	PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s contracts/tests -p 'test_*.py' -v

baseline-macos-build:
	cd baseline/MacHost && swift build -c release

baseline-macos-test:
	cd baseline/MacHost && swift test

baseline-macos-self-test: baseline-macos-build
	baseline/MacHost/.build/release/Telemachus --host-self-test
	baseline/MacHost/.build/release/Telemachus --transport-self-test
	baseline/MacHost/.build/release/Telemachus --reliability-self-test
	baseline/MacHost/.build/release/Telemachus --protocol-v1-self-test

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

release-tools-test:
	PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts/tests -v

require-evidence-serial:
	@test -n "$(strip $(EVIDENCE_SERIAL))" || (echo "error: set EVIDENCE_SERIAL explicitly" >&2; exit 2)

evidence-device-info: require-evidence-serial
	mkdir -p $(EVIDENCE_DIR)
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.device_info --serial $(EVIDENCE_SERIAL) --package $(EVIDENCE_PACKAGE) --output $(EVIDENCE_DIR)/device-info.json

soak-30m soak-2h soak-8h: require-evidence-serial
	mkdir -p $(EVIDENCE_DIR)/$@
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools python3 -m vibescreen_evidence.soak --serial $(EVIDENCE_SERIAL) --preset $(@:soak-%=%) --interval 30s --package $(EVIDENCE_PACKAGE) --telemetry-jsonl $(EVIDENCE_DIR)/$@/host-telemetry.jsonl --require-stream-telemetry --output-jsonl $(EVIDENCE_DIR)/$@/samples.jsonl --summary-json $(EVIDENCE_DIR)/$@/summary.json
