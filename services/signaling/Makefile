.PHONY: build test verify

build:
	go build -trimpath -o build/vibe-signaling ./cmd/vibe-signaling

test:
	go test -count=1 ./...

verify:
	test -z "$$(gofmt -l .)"
	go vet ./...
	go test -race -count=1 ./...
