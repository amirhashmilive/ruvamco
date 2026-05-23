# ── Stage 1: Builder ─────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: Runtime ─────────────────────────────────────────────
FROM python:3.11-slim

LABEL maintainer="Amir Hashmi <amir@ruvamco.io>"
LABEL org.opencontainers.image.description="RUVAMCO Async Provisioning Worker"

RUN groupadd -r ruvamco && useradd -r -g ruvamco -d /app ruvamco

WORKDIR /app
COPY --from=builder /install /usr/local
COPY . .

RUN chown -R ruvamco:ruvamco /app
USER ruvamco

ENTRYPOINT ["python", "main.py"]
