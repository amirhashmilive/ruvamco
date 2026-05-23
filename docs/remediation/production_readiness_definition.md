# RUVAMCO — Production Readiness Definition
**Meer Corporation — Operations & Compliance Standards**
**Version: 1.0 — GO-LIVE CRITERIA**

This document establishes the official **Production Readiness Definition** for RUVAMCO. For a deployment of the platform to be certified as "Production-Ready" and permitted to serve live enterprise traffic, it must satisfy all criteria listed across the five core operational domains.

---

## 1. Security & Compliance Standards

Zero-trust architecture and robust boundary protection are mandatory for all production endpoints.

| Requirement ID | Standard Name | Description | Verification Method |
|---|---|---|---|
| **SEC-REQ-01** | Asymmetric Cryptography | All JSON Web Tokens (JWT) must be signed with a private `RSA-4096` key and verified using public keys retrieved from a secure, version-controlled JSON Web Key Set (JWKS) endpoint. Symmetric `HS256` token validation is banned. | Code audit of `broker/auth.py` and Envoy JWT filter verification. |
| **SEC-REQ-02** | Least-Privilege IAM | AWS IAM roles must be strictly scoped to resource ARNs. Wildcards (`*`) for actions or resources in `dynamodb:*`, `s3:*`, `route53:*`, and `cloudfront:*` are prohibited. Separated Task Execution Roles and Task Roles must be used. | static IAM analysis utilizing `tfsec` or `checkov`. |
| **SEC-REQ-03** | Data In-Transit Encryption | All control plane communication (xDS gRPC on Port 18000) and data plane backend connections must run over TLS 1.3. Mutual TLS (mTLS) with SPIFFE/SPIRE-issued identity documents is required for proxy-to-sidecar communications. | TLS cipher suite scans (`nmap --script ssl-enum-ciphers`). |
| **SEC-REQ-04** | Vulnerability Ingestion Gates | Container images must undergo static vulnerability scans. No image containing `CRITICAL` or `HIGH` severity Common Vulnerabilities and Exposures (CVEs) with available patches may be pushed to the registry. | `trivy image` execution integrated in CI pipeline. |
| **SEC-REQ-05** | Credential Isolation | No production secrets, passwords, or API keys may be committed as default values in code, `.env` files, or Docker Compose setups. Credentials must be injected at runtime via AWS Secrets Manager or secure environment variables. | Automated git history scan (`git-leaks`). |

> [!WARNING]
> **Active Security Vulnerability Gate:**
> Production deployments are blocked until the current symmetric HS256 JWT key configuration in `broker/auth.py` is removed, and the wildcard IAM policies in `terraform/modules/control-plane/main.tf` are replaced with resource-level policies.

---

## 2. Reliability & High Availability

The system must absorb backend outages and traffic spikes without dropping requests or corrupting configuration state.

### 2.1 Sidecar Degraded-Mode Fallback
- **Rate Limit Sidecar**: The Go-based rate limiter sidecar must communicate with Redis for global sliding-window rate tracking. In the event of a Redis cluster outage, the sidecar must enter a **degraded mode**:
  - Automatically fall back to in-process memory-based limiting (`golang.org/x/time/rate`).
  - To prevent upstream service saturation during degraded operation, the allowed Request Per Second (RPS) threshold must automatically reduce by **50%**.
  - Metric `ratelimit_degraded_mode` must flip to `1`.
  - The sidecar must continually attempt to reconnect to Redis and auto-recover once available.
- **Auth Sidecar**: The Rust-based auth sidecar must cache JWKS keys locally in memory with a configurable TTL (default 5 minutes). If the broker/issuer is temporarily unreachable during a token verification call, the sidecar must continue to trust cached keys until the TTL expires, avoiding dependency cascading failure.

### 2.2 SQS Queue Resilience & DLQ
- The SQS provisioning queue must have a **Dead Letter Queue (DLQ)** attached.
- The `maxReceiveCount` must be set to `3`. If a message fails processing in the worker 3 times, it must automatically triage to the DLQ to prevent blocking the queue with "poison pill" messages.
- The queue's **Visibility Timeout** must be set to `300 seconds` (5 minutes) to ensure that slow provisioning operations (e.g., waiting for CloudFront distribution creation) do not result in duplicate workers picking up the same message.

### 2.3 Storage and Database Protection
- **DynamoDB Deletion Protection**: Deletion protection must be enabled on the `ruvamco-instances` table to prevent accidental data loss.
- **Auto-Scaling**: DynamoDB tables must be configured with target tracking auto-scaling (70% utilization target) or run in On-Demand capacity mode.

---

## 3. Observability & Monitoring

No black-box components are permitted. All services must output structured health, metrics, and trace telemetry.

```
                  ┌──────────────┐
                  │ Prometheus   │
                  └──────┬───────┘
                         │ Scrapes /metrics (Plaintext ONLY)
                         ▼
┌──────────────────────────────────────────────────┐
│             FastAPI / Go / Python Service        │
│ ┌──────────────┐ ┌──────────────┐ ┌────────────┐ │
│ │ /health/live │ │/health/ready │ │  /metrics  │ │
│ └──────────────┘ └──────────────┘ └────────────┘ │
└──────────────────────────────────────────────────┘
```

### 3.1 Health Check API Separation
Every service (Broker, Worker, Control Plane, Sidecars) must expose two distinct HTTP health endpoints:
1. **Liveness Probe** (`/health/live`):
   - Returns HTTP `200 OK` with JSON `{"status": "alive"}` immediately.
   - Purpose: Verifies the process is running, not deadlocked, and responding to HTTP requests.
2. **Readiness Probe** (`/health/ready`):
   - Performs active dependency checks (e.g., attempts simple ping to DynamoDB, SQS queue connection, Redis socket, S3 bucket list).
   - Returns HTTP `200 OK` only if all dependencies are verified.
   - Returns HTTP `503 Service Unavailable` with detailed dependency statuses if any checks fail.

### 3.2 Metrics Exposition
- JSON serialization of `/metrics` endpoints is **prohibited**. All services must use official Prometheus client libraries to expose plaintext metrics in the format:
  ```text
  # HELP metric_name description
  # TYPE metric_name type
  metric_name{label="value"} value
  ```
- **Scrape SLA**: Metric endpoints must respond in `< 50ms` under normal load.

### 3.3 Tracing and Logging Requirements
- **OpenTelemetry Integration**: The broker, worker, control plane, and sidecars must initialize the OpenTelemetry (OTEL) SDK and export trace telemetry to the configured collector.
- **Correlation IDs**: All requests entering the edge proxy must be assigned a unique `X-Request-ID`. This header must be propagated through all downstream calls:
  - Logged by Envoy.
  - Passed to the Auth and Rate Limit sidecars.
  - Attached to SQS messages in the worker.
  - Included in all structured JSON logs.
- **JSON Structured Logging**: Production stdout/stderr must print structured JSON lines containing fields: `timestamp`, `level`, `request_id`, `service_name`, and `message`. Plain string stdout prints are blocked.

---

## 4. Performance & Scalability SLA

The platform must meet strict latency and processing benchmarks to maintain production quality.

```
[YAML Commit] ──▶ [Broker API] ──▶ [SQS Queue] ──▶ [Worker Fleet] ──▶ [S3 Bucket Reload] ──▶ [xDS Push] ──▶ [Envoy Loaded]
  │                                                                                                             │
  └───────────────────────────────── TOTAL PROPAGATION SLA: < 30 SECONDS (p95) ─────────────────────────────────┘
```

- **Provisioning Time SLA (p95)**: The elapsed time between a PUT call on the Broker and the instance status changing to `active` must be `< 30 seconds` for Developer/Business plans (Route 53 records propagated), and `< 15 minutes` for Enterprise plans (CloudFront distribution creation and caching validation).
- **Configuration Propagation SLA**: Once a configuration is uploaded to the S3 context store and `/v1/reload` is invoked, the xDS control plane must push the configuration and all Envoy proxies in that fleet must load the new routes in `< 5 seconds`.
- **Database Query Safeguard**: Full table scans (`Table.scan()`) in DynamoDB are banned in hot paths. The control plane must use DynamoDB Queries (`Table.query()`) with partition keys or secondary indexes (GSI) to fetch instance contexts.

---

## 5. Deployment Governance & CI/CD Gates

Automation must be protected by explicit safety checks and deployment separation.

- **OIDC Authentication**: GitHub Actions CI/CD workflows must not use persistent `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` secrets. The CI runner must authenticate with AWS STS dynamically via OpenID Connect (OIDC) roles.
- **Production Environment Gates**:
  - Direct `terraform apply -auto-approve` on merge to `main` is **banned**.
  - Deployment jobs targeting production AWS accounts must reference a protected GitHub Environment (e.g., `production`).
  - Production deployments require explicit approval from at least one authorized team member.
- **Semantic Pinned Images**: Production Kubernetes/Terraform deployment files must not deploy images tagged with `:latest`. Image references must use explicit SemVer tags or the git commit SHA hash (e.g., `ruvamco/broker:v1.0.0-rc1` or `ruvamco/broker:sha-1f46354`).

---
*Meer Corporation Architecture Review Board — Certification Required prior to GA Tagging.*
