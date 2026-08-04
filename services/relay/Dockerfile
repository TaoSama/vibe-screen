FROM golang:1.24.13-alpine3.22@sha256:3641e0d9b931dc4f2f185dcd669c4679670e9277c8166a838ddb98a2d4389cb5 AS build
ARG VERSION=development
WORKDIR /src
COPY go.mod ./
COPY cmd ./cmd
COPY internal ./internal
RUN CGO_ENABLED=0 go build -buildvcs=false -trimpath -ldflags="-s -w -X main.version=${VERSION}" -o /out/vibe-relay ./cmd/vibe-relay

FROM scratch
COPY --from=build /out/vibe-relay /vibe-relay
USER 65532:65532
EXPOSE 8090
ENTRYPOINT ["/vibe-relay"]
CMD ["--config", "/etc/vibe-relay/config.json"]
