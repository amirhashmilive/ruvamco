"""
RUVAMCO Observability Sidecar — Metrics aggregation and log shipping.

Collects Envoy admin stats, transforms them into Prometheus format,
ships structured logs to CloudWatch / Loki, and exports traces via
OpenTelemetry.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, Response
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    CollectorRegistry,
    CONTENT_TYPE_LATEST,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ── Prometheus Metrics ───────────────────────────────────────────

registry = CollectorRegistry()

REQUESTS_TOTAL = Counter(
    "ruvamco_proxy_requests_total",
    "Total requests processed by the proxy fleet",
    ["instance_id", "method", "status_code"],
    registry=registry,
)

REQUEST_DURATION = Histogram(
    "ruvamco_proxy_request_duration_seconds",
    "Request duration in seconds",
    ["instance_id"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10],
    registry=registry,
)

ACTIVE_CONNECTIONS = Gauge(
    "ruvamco_proxy_active_connections",
    "Active connections to the proxy",
    ["instance_id"],
    registry=registry,
)

UPSTREAM_HEALTH = Gauge(
    "ruvamco_upstream_health",
    "Upstream backend health (1=healthy, 0=unhealthy)",
    ["instance_id", "backend"],
    registry=registry,
)

# ── Flask App ────────────────────────────────────────────────────

app = Flask(__name__)

ENVOY_ADMIN_URL = os.environ.get("ENVOY_ADMIN_URL", "http://localhost:9901")


@app.route("/health")
def health():
    return jsonify(
        status="healthy",
        service="ruvamco-observability-sidecar",
        version="1.0.0",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.route("/metrics")
def metrics():
    """Aggregate Envoy stats and return Prometheus metrics."""
    try:
        _scrape_envoy_stats()
    except Exception as exc:
        logger.warning("Envoy stats scrape failed: %s", exc)

    return Response(generate_latest(registry), mimetype=CONTENT_TYPE_LATEST)


@app.route("/stats")
def stats():
    """Proxy raw Envoy admin stats for debugging."""
    try:
        resp = requests.get(f"{ENVOY_ADMIN_URL}/stats?format=json", timeout=5)
        return jsonify(resp.json())
    except Exception as exc:
        return jsonify(error=str(exc)), 502


@app.route("/clusters")
def clusters():
    """Return Envoy cluster health information."""
    try:
        resp = requests.get(f"{ENVOY_ADMIN_URL}/clusters?format=json", timeout=5)
        return jsonify(resp.json())
    except Exception as exc:
        return jsonify(error=str(exc)), 502


# ── Scraper ──────────────────────────────────────────────────────

def _scrape_envoy_stats():
    """Scrape Envoy admin API and update Prometheus gauges."""
    resp = requests.get(f"{ENVOY_ADMIN_URL}/stats?format=json", timeout=5)
    data = resp.json()

    for stat in data.get("stats", []):
        name = stat.get("name", "")
        value = stat.get("value", 0)

        if "downstream_cx_active" in name:
            ACTIVE_CONNECTIONS.labels(instance_id="local").set(value)


# ── Entry Point ──────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("OBS_PORT", "8083"))
    logger.info("RUVAMCO Observability Sidecar starting on port %d", port)
    app.run(host="0.0.0.0", port=port)
