# syntax=docker/dockerfile:1.7
FROM busybox:1.35.0-uclibc AS busybox

FROM golang:1.26-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
ENV CGO_ENABLED=0 GOOS=linux
RUN go build -trimpath -ldflags='-s -w' -o /out/ozm-server  ./cmd/server \
 && go build -trimpath -ldflags='-s -w' -o /out/ozm-migrate ./cmd/migrate \
 && go build -trimpath -ldflags='-s -w' -o /out/ozm-dcextract ./cmd/dcextract

FROM gcr.io/distroless/static-debian12:nonroot
WORKDIR /app
COPY --from=busybox /bin/sh /bin/sh
COPY --from=build /out/ozm-server /app/ozm-server
COPY --from=build /out/ozm-migrate /app/ozm-migrate
COPY --from=build /src/dicts /config/dicts
EXPOSE 8080
USER 65532:65532
ENTRYPOINT ["/app/ozm-server"]
