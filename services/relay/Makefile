VERSION ?= 0.1.0
OUTPUT ?= bin/vibe-relay

.PHONY: build test verify clean

build:
	mkdir -p "$(dir $(OUTPUT))"
	CGO_ENABLED=0 go build -buildvcs=false -trimpath -ldflags="-s -w -X main.version=$(VERSION)" -o "$(OUTPUT)" ./cmd/vibe-relay

test:
	go test ./...
	python3 -m unittest discover -s integration -p 'test_*.py'

verify:
	test -z "$$(gofmt -l .)"
	go vet ./...
	go test -race -count=1 ./...
	python3 -m unittest discover -s integration -p 'test_*.py'

clean:
	rm -f "$(OUTPUT)"
