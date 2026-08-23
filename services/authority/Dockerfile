FROM golang:1.25.5-alpine3.22@sha256:3587db7cc96576822c606d119729370dbf581931c5f43ac6d3fa03ab4ed85a10 AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download && go mod verify
COPY cmd ./cmd
COPY internal ./internal
ARG VERSION=0.1.0
RUN CGO_ENABLED=0 go build -trimpath \
    -ldflags="-s -w -X main.version=${VERSION}" \
    -o /out/vibe-authority ./cmd/vibe-authority

FROM scratch
COPY --from=build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY --from=build /out/vibe-authority /vibe-authority
COPY config.container.json /etc/vibe-screen/authority.json
COPY migrations /usr/share/vibe-screen/migrations
USER 65532:65532
EXPOSE 8091
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
    CMD ["/vibe-authority", "--healthcheck", "http://127.0.0.1:8091/readyz"]
ENTRYPOINT ["/vibe-authority"]
CMD ["--config", "/etc/vibe-screen/authority.json"]
