"""
RUVAMCO Broker — Pydantic domain models.

Defines the canonical request / response shapes for the Open Service Broker
API as well as internal data transfer objects used by the Broker ↔ Worker
pipeline.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator


# ── Enums ────────────────────────────────────────────────────────

class PlanId(str, Enum):
    DEVELOPER = "developer"
    BUSINESS = "business"
    ENTERPRISE = "enterprise"


class InstanceStatus(str, Enum):
    PROVISIONING = "provisioning"
    ACTIVE = "active"
    FAILED = "failed"
    DEPROVISIONING = "deprovisioning"
    DELETED = "deleted"


# ── Nested Parameter Models ─────────────────────────────────────

class BackendConfig(BaseModel):
    type: str = Field(..., description="Backend type: kubernetes | ec2 | lambda")
    target: str = Field(..., description="Fully-qualified backend address")
    port: int = Field(8080, ge=1, le=65535)
    health_check_path: str = "/health"
    protocol: str = "HTTP2"


class RateLimitConfig(BaseModel):
    requests_per_second: int = Field(100, ge=1, le=1_000_000)
    burst: int = Field(200, ge=1)
    per: str = "ip"  # ip | api_key | user


class AuthConfig(BaseModel):
    type: str = "none"  # none | jwt | mtls | api_key
    jwks_url: Optional[str] = None
    issuer: Optional[str] = None
    audiences: List[str] = []


class TimeoutConfig(BaseModel):
    request: int = Field(30, ge=1, le=300, description="Total request timeout in seconds")
    connection: int = Field(5, ge=1, le=60)
    idle: int = Field(300, ge=1, le=3600)


class RetryConfig(BaseModel):
    attempts: int = Field(3, ge=0, le=10)
    per_try_timeout: int = Field(10, ge=1)
    retry_on: str = "5xx,reset,connect-failure"


class CircuitBreakerConfig(BaseModel):
    max_connections: int = Field(1024, ge=1)
    max_pending_requests: int = Field(1024, ge=1)
    max_requests: int = Field(1024, ge=1)
    max_retries: int = Field(3, ge=0)


class CorsConfig(BaseModel):
    allow_origins: List[str] = ["*"]
    allow_methods: List[str] = ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    allow_headers: List[str] = ["*"]
    max_age: int = 86400


class ProvisionParameters(BaseModel):
    """Top-level parameters embedded in a provision request."""
    domain: str
    backend: BackendConfig
    rate_limit: Optional[RateLimitConfig] = None
    auth: Optional[AuthConfig] = None
    timeouts: Optional[TimeoutConfig] = None
    retries: Optional[RetryConfig] = None
    circuit_breaker: Optional[CircuitBreakerConfig] = None
    cors: Optional[CorsConfig] = None
    plan_id: PlanId = PlanId.DEVELOPER
    custom_headers: Dict[str, str] = {}
    tags: Dict[str, str] = {}


# ── API Request / Response Models ────────────────────────────────

class ProvisionRequest(BaseModel):
    """Open Service Broker provision request body."""
    service_id: str = "edge-proxy-service"
    plan_id: PlanId = PlanId.DEVELOPER
    context: Dict[str, Any] = {}
    parameters: ProvisionParameters

    @validator("parameters", pre=True)
    def _wrap_parameters(cls, v):
        if isinstance(v, dict):
            return ProvisionParameters(**v)
        return v


class ServiceInstance(BaseModel):
    """Persistent representation of a provisioned instance."""
    instance_id: str
    service_id: str
    plan_id: PlanId
    parameters: Dict[str, Any]
    context: Dict[str, Any] = {}
    status: InstanceStatus = InstanceStatus.PROVISIONING
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    operation: str = ""

    class Config:
        use_enum_values = True


class ProvisionTask(BaseModel):
    """Message queued for async worker processing."""
    task_id: str
    operation: str  # provision | deprovision | update
    instance_id: str
    parameters: Dict[str, Any] = {}
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    retry_count: int = 0
    max_retries: int = 3


class OperationStatus(BaseModel):
    state: str  # in progress | succeeded | failed
    description: str
    last_operation: Optional[str] = None
