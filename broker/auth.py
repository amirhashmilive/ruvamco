"""
RUVAMCO Broker — Authentication & Authorization.

Provides API-key and JWT bearer-token validation as FastAPI
dependency-injection callables.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────

API_KEY_HEADER = APIKeyHeader(name="X-Broker-API-Key", auto_error=False)
BEARER_SCHEME = HTTPBearer(auto_error=False)

_VALID_API_KEYS: set[str] = set(
    filter(None, os.environ.get("RUVAMCO_API_KEYS", "dev-api-key-change-me").split(","))
)

JWT_SECRET = os.environ.get("JWT_SECRET", "change-me-in-production")
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
JWT_EXPIRY_MINUTES = int(os.environ.get("JWT_EXPIRY_MINUTES", "60"))


# ── Helpers ──────────────────────────────────────────────────────

def _constant_time_compare(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def create_jwt_token(subject: str, extra_claims: dict | None = None) -> str:
    """Mint a signed JWT for service-to-service or CLI auth."""
    now = datetime.utcnow()
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=JWT_EXPIRY_MINUTES),
        "iss": "ruvamco-broker",
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_jwt_token(token: str) -> dict:
    """Decode and validate a JWT.  Raises on expiry or bad signature."""
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM], issuer="ruvamco-broker")


# ── FastAPI Dependencies ─────────────────────────────────────────

async def verify_api_key(
    api_key: Optional[str] = Security(API_KEY_HEADER),
    bearer: Optional[HTTPAuthorizationCredentials] = Security(BEARER_SCHEME),
) -> str:
    """Accept either ``X-Broker-API-Key`` header or ``Authorization: Bearer <jwt>``."""

    # 1) Try API key
    if api_key:
        for valid_key in _VALID_API_KEYS:
            if _constant_time_compare(api_key, valid_key):
                return f"apikey:{hashlib.sha256(api_key.encode()).hexdigest()[:8]}"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    # 2) Try Bearer JWT
    if bearer:
        try:
            claims = decode_jwt_token(bearer.credentials)
            return f"jwt:{claims.get('sub', 'unknown')}"
        except jwt.ExpiredSignatureError:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired")
        except jwt.InvalidTokenError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {exc}")

    # 3) No credentials at all
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing authentication — provide X-Broker-API-Key or Bearer token",
    )
