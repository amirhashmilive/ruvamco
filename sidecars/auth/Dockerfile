# ── Build ────────────────────────────────────────────────────────
FROM rust:1.77-slim AS builder

RUN apt-get update && apt-get install -y pkg-config libssl-dev && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY Cargo.toml ./
COPY src/ ./src/

RUN cargo build --release

# ── Runtime ──────────────────────────────────────────────────────
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y ca-certificates && rm -rf /var/lib/apt/lists/*
RUN groupadd -r ruvamco && useradd -r -g ruvamco ruvamco

COPY --from=builder /build/target/release/ruvamco-auth-sidecar /usr/local/bin/ruvamco-auth

RUN chmod +x /usr/local/bin/ruvamco-auth
USER ruvamco

EXPOSE 8081

HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD curl -sf http://localhost:8081/health || exit 1

ENTRYPOINT ["ruvamco-auth"]
