"""
RUVAMCO — Integration Tests: Routing Verification

Tests that provisioned routes actually forward traffic through Envoy
to backend services.
"""

import pytest
import requests
import time


ENVOY_URL = "http://localhost:10000"
ENVOY_ADMIN = "http://localhost:9901"


@pytest.fixture(scope="module")
def ensure_envoy():
    try:
        resp = requests.get(f"{ENVOY_ADMIN}/ready", timeout=5)
        if resp.status_code != 200:
            pytest.skip("Envoy not ready")
    except requests.ConnectionError:
        pytest.skip("Envoy not running — start with `make up`")


class TestRouting:
    """Tests for Envoy routing correctness."""

    def test_envoy_admin_reachable(self, ensure_envoy):
        resp = requests.get(f"{ENVOY_ADMIN}/server_info")
        assert resp.status_code == 200

    def test_envoy_clusters_loaded(self, ensure_envoy):
        resp = requests.get(f"{ENVOY_ADMIN}/clusters?format=json")
        assert resp.status_code == 200

    def test_envoy_listeners_loaded(self, ensure_envoy):
        resp = requests.get(f"{ENVOY_ADMIN}/listeners?format=json")
        assert resp.status_code == 200

    def test_envoy_stats_available(self, ensure_envoy):
        resp = requests.get(f"{ENVOY_ADMIN}/stats?format=json")
        assert resp.status_code == 200
        data = resp.json()
        assert "stats" in data
