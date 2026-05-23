"""
RUVAMCO — Broker Unit Tests

Tests for the Service Broker API: provisioning, deprovisioning,
catalog, status polling, and input validation.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime


# ── Model Tests ──────────────────────────────────────────────────

class TestProvisionRequest:
    """Tests for ProvisionRequest model validation."""

    def test_valid_developer_plan(self):
        from broker.models import ProvisionRequest, ProvisionParameters, BackendConfig

        params = ProvisionParameters(
            domain="api.example.com",
            backend=BackendConfig(target="my-service.default.svc.cluster.local", type="kubernetes"),
        )
        req = ProvisionRequest(parameters=params)
        assert req.plan_id == "developer"
        assert req.service_id == "edge-proxy-service"

    def test_enterprise_plan_with_auth(self):
        from broker.models import (
            ProvisionRequest, ProvisionParameters,
            BackendConfig, AuthConfig, PlanId,
        )

        params = ProvisionParameters(
            domain="api.example.com",
            backend=BackendConfig(target="backend.internal", port=8443, protocol="HTTP2", type="kubernetes"),
            auth=AuthConfig(type="jwt", jwks_url="https://auth.example.com/.well-known/jwks.json"),
            plan_id=PlanId.ENTERPRISE,
        )
        req = ProvisionRequest(plan_id=PlanId.ENTERPRISE, parameters=params)
        assert req.plan_id == "enterprise"
        assert req.parameters.auth.type == "jwt"

    def test_invalid_port_rejected(self):
        from broker.models import BackendConfig
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            BackendConfig(target="svc.local", port=99999, type="kubernetes")

    def test_rate_limit_validation(self):
        from broker.models import RateLimitConfig
        from pydantic import ValidationError

        config = RateLimitConfig(requests_per_second=500, burst=1000)
        assert config.requests_per_second == 500

        with pytest.raises(ValidationError):
            RateLimitConfig(requests_per_second=-1)


class TestServiceInstance:
    """Tests for ServiceInstance model."""

    def test_default_status_is_provisioning(self):
        from broker.models import ServiceInstance

        instance = ServiceInstance(
            instance_id="test-001",
            service_id="edge-proxy-service",
            plan_id="developer",
            parameters={"domain": "test.com"},
        )
        assert instance.status == "provisioning"

    def test_serialization_round_trip(self):
        from broker.models import ServiceInstance

        instance = ServiceInstance(
            instance_id="test-002",
            service_id="edge-proxy-service",
            plan_id="business",
            parameters={"domain": "api.test.com"},
            operation="provision-abc123",
        )
        data = instance.dict()
        restored = ServiceInstance(**data)
        assert restored.instance_id == "test-002"
        assert restored.operation == "provision-abc123"


class TestProvisionTask:
    """Tests for ProvisionTask model."""

    def test_default_retry_count(self):
        from broker.models import ProvisionTask

        task = ProvisionTask(
            task_id="task-001",
            operation="provision",
            instance_id="inst-001",
        )
        assert task.retry_count == 0
        assert task.max_retries == 3


# ── Auth Tests ───────────────────────────────────────────────────

class TestAuth:
    """Tests for authentication module."""

    def test_jwt_round_trip(self):
        from broker.auth import create_jwt_token, decode_jwt_token

        token = create_jwt_token("test-user", {"role": "admin"})
        claims = decode_jwt_token(token)
        assert claims["sub"] == "test-user"
        assert claims["role"] == "admin"
        assert claims["iss"] == "ruvamco-broker"

    def test_expired_token_rejected(self):
        import jwt as pyjwt
        from broker.auth import decode_jwt_token, JWT_SECRET, JWT_ALGORITHM

        expired = pyjwt.encode(
            {"sub": "expired", "exp": 0, "iss": "ruvamco-broker"},
            JWT_SECRET,
            algorithm=JWT_ALGORITHM,
        )
        with pytest.raises(pyjwt.ExpiredSignatureError):
            decode_jwt_token(expired)


# ── Plan Limit Tests ─────────────────────────────────────────────

class TestPlanLimits:
    """Tests for plan-based validation."""

    @pytest.mark.asyncio
    async def test_developer_plan_rejects_high_rps(self):
        from broker.main import validate_plan_limits
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await validate_plan_limits("developer", {"rate_limit": {"requests_per_second": 500}})
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_enterprise_plan_allows_high_rps(self):
        from broker.main import validate_plan_limits

        # Should not raise
        await validate_plan_limits("enterprise", {"rate_limit": {"requests_per_second": 50000}})
