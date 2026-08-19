FROM golang:1.25.5-alpine3.22@sha256:3587db7cc96576822c606d119729370dbf581931c5f43ac6d3fa03ab4ed85a10 AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download && go mod verify
COPY cmd ./cmd
COPY internal ./internal
ARG VERSION=0.1.0
RUN CGO_ENABLED=0 go build -trimpath \
    -ldflags="-s -w -X main.version=${VERSION}" \
    -o /out/vibe-signaling ./cmd/vibe-signaling

FROM scratch
COPY --from=build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY --from=build /out/vibe-signaling /vibe-signaling
COPY migrations/001_signaling.sql /usr/share/vibe-screen/migrations/001_signaling.sql
USER 65532:65532
EXPOSE 8088
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
    CMD ["/vibe-signaling", "--healthcheck", "http://127.0.0.1:8088/readyz"]
ENTRYPOINT ["/vibe-signaling"]
CMD ["--config", "/etc/vibe-screen/signaling.json"]
