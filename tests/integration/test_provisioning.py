"""
RUVAMCO — Integration Tests: Provisioning Pipeline

Tests the full provisioning path from Broker API → SQS → Worker →
S3 Context → Control Plane, using local Docker services.
"""

import json
import time
import pytest
import requests
from unittest.mock import patch


# These tests expect the local docker-compose stack to be running
BROKER_URL = "http://localhost:8080"
CONTROL_PLANE_URL = "http://localhost:8081"

API_KEY = "dev-api-key-change-me"
HEADERS = {
    "X-Broker-API-Key": API_KEY,
    "Content-Type": "application/json",
}


@pytest.fixture(scope="module")
def ensure_services():
    """Check that local services are available."""
    for url, name in [(BROKER_URL, "Broker"), (CONTROL_PLANE_URL, "Control Plane")]:
        try:
            resp = requests.get(f"{url}/health", timeout=5)
            assert resp.status_code == 200, f"{name} health check failed"
        except requests.ConnectionError:
            pytest.skip(f"{name} not running at {url} — start with `make up`")


class TestProvisioningPipeline:
    """End-to-end provisioning pipeline tests."""

    INSTANCE_ID = f"integration-test-{int(time.time())}"

    def test_01_catalog_returns_plans(self, ensure_services):
        resp = requests.get(f"{BROKER_URL}/v2/catalog", headers=HEADERS)
        assert resp.status_code == 200

        catalog = resp.json()
        services = catalog["services"]
        assert len(services) > 0
        assert services[0]["id"] == "edge-proxy-service"

        plans = services[0]["plans"]
        plan_ids = {p["id"] for p in plans}
        assert {"developer", "business", "enterprise"} == plan_ids

    def test_02_provision_instance(self, ensure_services):
        payload = {
            "service_id": "edge-proxy-service",
            "plan_id": "developer",
            "context": {"platform": "test"},
            "parameters": {
                "domain": "integration-test.example.com",
                "backend": {
                    "type": "kubernetes",
                    "target": "test-svc.default.svc.cluster.local",
                    "port": 8080,
                },
            },
        }

        resp = requests.put(
            f"{BROKER_URL}/v2/service_instances/{self.INSTANCE_ID}",
            headers=HEADERS,
            json=payload,
        )
        assert resp.status_code == 202

        body = resp.json()
        assert "operation" in body
        assert body["operation"].startswith("provision-")

    def test_03_poll_operation_status(self, ensure_services):
        """Poll until provisioning completes or timeout."""
        for _ in range(30):
            resp = requests.get(
                f"{BROKER_URL}/v2/service_instances/{self.INSTANCE_ID}/last_operation",
                headers=HEADERS,
            )
            assert resp.status_code == 200

            state = resp.json()["state"]
            if state in ("succeeded", "failed"):
                break
            time.sleep(1)

    def test_04_duplicate_provision_rejected(self, ensure_services):
        payload = {
            "service_id": "edge-proxy-service",
            "plan_id": "developer",
            "parameters": {
                "domain": "dupe.example.com",
                "backend": {"type": "kubernetes", "target": "svc.local", "port": 8080},
            },
        }

        resp = requests.put(
            f"{BROKER_URL}/v2/service_instances/{self.INSTANCE_ID}",
            headers=HEADERS,
            json=payload,
        )
        assert resp.status_code == 409

    def test_05_deprovision_instance(self, ensure_services):
        resp = requests.delete(
            f"{BROKER_URL}/v2/service_instances/{self.INSTANCE_ID}",
            headers=HEADERS,
            params={"service_id": "edge-proxy-service", "plan_id": "developer"},
        )
        assert resp.status_code == 200

        body = resp.json()
        assert "operation" in body


class TestRoutingIntegration:
    """Tests for control-plane routing configuration."""

    def test_control_plane_status(self, ensure_services):
        resp = requests.get(f"{CONTROL_PLANE_URL}/v1/status")
        assert resp.status_code == 200

        body = resp.json()
        assert body["status"] == "healthy"
        assert body["service"] == "ruvamco-control-plane"

    def test_list_instances(self, ensure_services):
        resp = requests.get(f"{CONTROL_PLANE_URL}/v1/instances")
        assert resp.status_code == 200
        assert "instances" in resp.json()
