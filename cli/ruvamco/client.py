"""
RUVAMCO CLI — HTTP client for the Service Broker API.

Wraps requests.Session with retry logic, authentication header
injection, and structured error handling.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import RuvamcoConfig

logger = logging.getLogger(__name__)


class RuvamcoClient:
    """Authenticated HTTP client for the RUVAMCO Broker API."""

    def __init__(self, config: Optional[RuvamcoConfig] = None):
        self.config = config or RuvamcoConfig.load()
        self.session = self._build_session()

    def _build_session(self) -> requests.Session:
        session = requests.Session()

        # Retry strategy
        retries = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "PUT", "DELETE"],
        )
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        # Auth header
        token = self.config.get_token()
        if token:
            session.headers.update({"Authorization": f"Bearer {token}"})

        api_key = self.config.api_key
        if api_key:
            session.headers.update({"X-Broker-API-Key": api_key})

        session.headers.update({
            "Content-Type": "application/json",
            "User-Agent": f"ruvamco-cli/1.0.0",
        })

        return session

    @property
    def base_url(self) -> str:
        return self.config.api_endpoint.rstrip("/")

    # ── Service Broker Operations ────────────────────────────────

    def provision(self, instance_id: str, config: Dict[str, Any]) -> Dict:
        """PUT /v2/service_instances/{instance_id}"""
        resp = self.session.put(
            f"{self.base_url}/v2/service_instances/{instance_id}",
            json=config,
        )
        resp.raise_for_status()
        return resp.json()

    def get_status(self, instance_id: str, operation: Optional[str] = None) -> Dict:
        """GET /v2/service_instances/{instance_id}/last_operation"""
        params = {"operation": operation} if operation else {}
        resp = self.session.get(
            f"{self.base_url}/v2/service_instances/{instance_id}/last_operation",
            params=params,
        )
        resp.raise_for_status()
        return resp.json()

    def delete(self, instance_id: str, service_id: str, plan_id: str) -> Dict:
        """DELETE /v2/service_instances/{instance_id}"""
        resp = self.session.delete(
            f"{self.base_url}/v2/service_instances/{instance_id}",
            params={"service_id": service_id, "plan_id": plan_id},
        )
        resp.raise_for_status()
        return resp.json()

    def list_instances(self) -> List[Dict]:
        """GET /v1/instances (control-plane endpoint)"""
        resp = self.session.get(f"{self.base_url}/v1/instances")
        resp.raise_for_status()
        return resp.json().get("instances", [])

    def get_catalog(self) -> Dict:
        """GET /v2/catalog"""
        resp = self.session.get(f"{self.base_url}/v2/catalog")
        resp.raise_for_status()
        return resp.json()

    def get_instance_config(self, instance_id: str) -> Dict:
        """GET /v1/instances/{instance_id}/config"""
        resp = self.session.get(f"{self.base_url}/v1/instances/{instance_id}/config")
        resp.raise_for_status()
        return resp.json()
