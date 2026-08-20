FROM golang:1.24.13-alpine3.22@sha256:3641e0d9b931dc4f2f185dcd669c4679670e9277c8166a838ddb98a2d4389cb5 AS build
ARG VERSION=development
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download && go mod verify
COPY cmd ./cmd
COPY internal ./internal
COPY migrations ./migrations
RUN CGO_ENABLED=0 go build -buildvcs=false -trimpath -ldflags="-s -w -X main.version=${VERSION}" -o /out/vibe-relay ./cmd/vibe-relay

FROM scratch
COPY --from=build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY --from=build /out/vibe-relay /vibe-relay
COPY migrations/001_relay.sql /usr/share/vibe-screen/migrations/001_relay.sql
USER 65532:65532
EXPOSE 8090
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
    CMD ["/vibe-relay", "--healthcheck", "http://127.0.0.1:8090/readyz"]
ENTRYPOINT ["/vibe-relay"]
CMD ["--config", "/etc/vibe-relay/config.json"]
