# RUVAMCO API Reference

## Authentication

All API requests require one of:

| Method | Header | Format |
|--------|--------|--------|
| API Key | `X-Broker-API-Key` | Raw key string |
| JWT | `Authorization` | `Bearer <token>` |

## Base URL

```
https://broker.ruvamco.io
```

---

## Catalog

### `GET /v2/catalog`

Returns available services and plans.

**Response** `200 OK`:
```json
{
  "services": [{
    "id": "edge-proxy-service",
    "name": "RUVAMCO Edge Load Balancer",
    "description": "Self-service edge proxy with authentication, rate limiting, and observability",
    "bindable": true,
    "plans": [
      {"id": "developer", "name": "Developer", "description": "Single region, 100 RPS"},
      {"id": "business", "name": "Business", "description": "Multi-region, 10,000 RPS"},
      {"id": "enterprise", "name": "Enterprise", "description": "Global, 100k+ RPS, mTLS, WAF"}
    ]
  }]
}
```

---

## Provisioning

### `PUT /v2/service_instances/{instance_id}`

Provision a new edge proxy instance. Returns `202 Accepted` (async).

**Request Body**:
```json
{
  "service_id": "edge-proxy-service",
  "plan_id": "developer",
  "context": {"platform": "kubernetes", "namespace": "default"},
  "parameters": {
    "domain": "api.example.com",
    "backend": {
      "type": "kubernetes",
      "target": "my-service.default.svc.cluster.local",
      "port": 8080,
      "protocol": "HTTP2",
      "health_check_path": "/health"
    },
    "rate_limit": {"requests_per_second": 100, "burst": 200, "per": "ip"},
    "auth": {"type": "jwt", "jwks_url": "https://auth.example.com/.well-known/jwks.json"},
    "timeouts": {"request": 30, "connection": 5, "idle": 300},
    "retries": {"attempts": 3, "per_try_timeout": 10, "retry_on": "5xx,reset"},
    "circuit_breaker": {"max_connections": 1024, "max_pending_requests": 1024},
    "cors": {"allow_origins": ["*"], "allow_methods": ["GET", "POST"]},
    "custom_headers": {"X-Service": "my-api"},
    "tags": {"team": "backend"}
  }
}
```

**Response** `202 Accepted`:
```json
{
  "operation": "provision-a1b2c3d4",
  "dashboard_url": "https://ruvamco.internal/instances/my-instance"
}
```

**Error Responses**:
- `409 Conflict` — Instance already exists
- `422 Unprocessable Entity` — Parameters exceed plan limits
- `401 Unauthorized` — Missing or invalid credentials

---

## Status Polling

### `GET /v2/service_instances/{instance_id}/last_operation`

Poll the status of an async operation.

**Query Parameters**: `operation` (optional)

**Response** `200 OK`:
```json
{
  "state": "in progress",
  "description": "Instance is provisioning",
  "last_operation": "provision-a1b2c3d4"
}
```

States: `in progress`, `succeeded`, `failed`

---

## Deprovisioning

### `DELETE /v2/service_instances/{instance_id}`

**Query Parameters**: `service_id`, `plan_id`

**Response** `200 OK`:
```json
{"operation": "deprovision-e5f6g7h8"}
```

---

## Health & Metrics

### `GET /health`

**Response** `200 OK`:
```json
{"status": "healthy", "service": "ruvamco-broker", "timestamp": "2024-01-01T00:00:00Z"}
```

### `GET /metrics`

Returns Prometheus-compatible metrics.

---

## Plan Limits

| Parameter | Developer | Business | Enterprise |
|-----------|-----------|----------|------------|
| Max RPS | 100 | 10,000 | 100,000 |
| Max Regions | 1 | 3 | 10 |
| Auth Types | API Key | JWT, API Key | JWT, mTLS, API Key |
| CDN | ✗ | ✗ | ✓ |
| WAF | ✗ | ✗ | ✓ |
| SLA | 99.9% | 99.95% | 99.99% |
