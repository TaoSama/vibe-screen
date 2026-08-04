FROM golang:1.24.13-alpine3.22@sha256:3641e0d9b931dc4f2f185dcd669c4679670e9277c8166a838ddb98a2d4389cb5 AS build
WORKDIR /src
COPY go.mod ./
COPY cmd ./cmd
COPY internal ./internal
ARG VERSION=0.1.0
RUN CGO_ENABLED=0 go build -trimpath \
    -ldflags="-s -w -X main.version=${VERSION}" \
    -o /out/vibe-signaling ./cmd/vibe-signaling

FROM scratch
COPY --from=build /out/vibe-signaling /vibe-signaling
USER 65532:65532
ENTRYPOINT ["/vibe-signaling"]
CMD ["--config", "/etc/vibe-screen/signaling.json"]
