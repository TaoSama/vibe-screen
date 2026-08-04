.PHONY: install test verify build-debug build-release release clean

HVIGOR := $(shell command -v hvigorw 2>/dev/null)
VERSION := 0.1.0

install:
	pnpm install --frozen-lockfile

test:
	pnpm test

verify:
	pnpm verify

build-debug:
	@test -n "$(HVIGOR)" || (echo "hvigorw not found; open this directory in DevEco Studio or add its command-line tools to PATH" >&2; exit 2)
	$(HVIGOR) --mode module -p module=entry@default -p product=default -p buildMode=debug assembleHap

build-release:
	@test -n "$(HVIGOR)" || (echo "hvigorw not found; open this directory in DevEco Studio or add its command-line tools to PATH" >&2; exit 2)
	$(HVIGOR) --mode module -p module=entry@default -p product=default -p buildMode=release assembleHap

release: build-release
	@mkdir -p dist/$(VERSION)
	@find entry/build -name '*.hap' -type f -exec cp {} dist/$(VERSION)/vibe-screen-harmony-$(VERSION).hap \;
	@shasum -a 256 dist/$(VERSION)/vibe-screen-harmony-$(VERSION).hap > dist/$(VERSION)/SHA256SUMS

clean:
	rm -rf .test-dist dist entry/build build

