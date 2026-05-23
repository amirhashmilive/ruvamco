# ── Stage 1: Builder ─────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: Runtime ─────────────────────────────────────────────
FROM python:3.11-slim

LABEL maintainer="Amir Hashmi <amir@ruvamco.io>"
LABEL org.opencontainers.image.description="RUVAMCO Envoy Control Plane"

RUN groupadd -r ruvamco && useradd -r -g ruvamco -d /app ruvamco

WORKDIR /app
COPY --from=builder /install /usr/local
COPY . .

RUN chown -R ruvamco:ruvamco /app
USER ruvamco

EXPOSE 8080 18000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"

ENTRYPOINT ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
