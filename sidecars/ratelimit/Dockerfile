# ── Build ────────────────────────────────────────────────────────
FROM golang:1.21-alpine AS builder

RUN apk add --no-cache git

WORKDIR /build
COPY go.mod ./
# RUN go mod download  # uncomment when go.sum is generated
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o ruvamco-ratelimit .

# ── Runtime ──────────────────────────────────────────────────────
FROM alpine:3.19

RUN apk add --no-cache ca-certificates curl
RUN addgroup -S ruvamco && adduser -S -G ruvamco ruvamco

COPY --from=builder /build/ruvamco-ratelimit /usr/local/bin/

USER ruvamco

EXPOSE 8082

HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD curl -sf http://localhost:8082/health || exit 1

ENTRYPOINT ["ruvamco-ratelimit"]
