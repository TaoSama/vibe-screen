.PHONY: install test verify ci doctor require-build-environment sync-project build-debug build-release release clean

HVIGOR ?= $(shell command -v hvigorw 2>/dev/null || command -v hvigor 2>/dev/null)
OHPM ?= $(shell command -v ohpm 2>/dev/null)
VERSION := 0.1.0

install:
	pnpm install --frozen-lockfile

test:
	pnpm test

verify:
	pnpm verify

ci: install verify

doctor:
	@printf 'hvigor: %s\n' "$(if $(HVIGOR),$(HVIGOR),not found)"
	@printf 'ohpm: %s\n' "$(if $(OHPM),$(OHPM),not found)"

require-build-environment:
	@test -n "$(HVIGOR)" || (echo "HarmonyOS build blocked: hvigorw/hvigor not found; install DevEco Studio and its command-line tools" >&2; exit 2)
	@test -n "$(OHPM)" || (echo "HarmonyOS build blocked: ohpm not found; install the DevEco-managed HarmonyOS SDK tools" >&2; exit 2)

sync-project: require-build-environment
	$(OHPM) install

build-debug: sync-project
	$(HVIGOR) --mode module -p module=entry@default -p product=default -p buildMode=debug assembleHap

build-release: sync-project
	$(HVIGOR) --mode module -p module=entry@default -p product=default -p buildMode=release assembleHap

release: build-release
	@mkdir -p dist/$(VERSION)
	@find entry/build -name '*.hap' -type f -exec cp {} dist/$(VERSION)/vibe-screen-harmony-$(VERSION).hap \;
	@shasum -a 256 dist/$(VERSION)/vibe-screen-harmony-$(VERSION).hap > dist/$(VERSION)/SHA256SUMS

clean:
	rm -rf .test-dist dist entry/build build
