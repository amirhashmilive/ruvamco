# RUVAMCO — Production-Grade Remediation & Hardening Plan
**Meer Corporation — Confidential**
**Review Level: MIT Lab / Hyperscale Infrastructure Audit**
**Prepared by: Principal Distributed Systems Architect & Production Security Engineer**
**Date: 2026-05-23**
**Version: 2.0 — PLAN ONLY — NO CODE CHANGES**

---

## 1. Executive Summary

RUVAMCO is a distributed edge proxy provisioning platform designed to operate at hyperscale — delivering self-service Envoy-based load balancers with authentication, rate limiting, and observability sidecars, orchestrated via a dynamic xDS control plane.

The platform demonstrates strong architectural intent: the Open Service Broker pattern is sound, the Jinja2-based xDS template pipeline is extensible, and the multi-language sidecar strategy (Rust for auth, Go for rate limiting, Python for observability) is well-suited for independent scaling. The Terraform module layout and DynamoDB/SQS/S3 state model are industry-standard.

However, a comprehensive code and infrastructure audit reveals that **RUVAMCO is not production-deployable in its current state.** The gap is not cosmetic — there are critical security vulnerabilities, non-functional subsystems presented as implemented, protocol violations in the xDS layer, and infrastructure anti-patterns that would constitute severe findings in any enterprise security review.

**This plan defines a six-phase remediation strategy** to bring the platform to production-grade status, suitable for multi-region deployment, enterprise customer workloads, and SOC 2 / zero-trust compliance review.

> [!CAUTION]
> The current main branch contains active security vulnerabilities including a symmetric HS256 JWT secret with a hardcoded default (`change-me-in-production`), wildcard IAM policies (`dynamodb:*`, `s3:*`, `route53:*` with `Resource: "*"`), and a gRPC control plane accepting connections on an insecure (non-TLS) port. **No production traffic should be served until Phase 1–3 are complete.**

---

## 2. Current Architecture Findings

### 2.1 System Overview (As-Built)

```
Internet → Envoy Proxy (port 10000)
              ↕ xDS/ADS gRPC (port 18000, INSECURE)
         Control Plane (FastAPI + gRPC)
              ↕ S3 (context storage)
              ↕ DynamoDB (instance state)
         Broker API (FastAPI, port 8080)
              ↕ SQS → Worker
                       ↕ Route53 / CloudFront / S3

Sidecars (intended but non-functional):
  - Auth Sidecar (Rust/Axum, port 8081) — JWKS refresh is a stub
  - Rate Limit Sidecar (Go, port 8082) — Redis imported but NOT connected
  - Observability Sidecar (Python/Flask, port 8083) — scrapes Envoy admin, hardcodes instance_id="local"
```

### 2.2 Critical Gaps vs. Intended Architecture

| Component | Intended | Actual State |
|---|---|---|
| Auth Sidecar JWKS | Fetches, caches, rotates keys | `refresh_jwks()` returns `Ok(())` immediately — **no-op stub** |
| Rate Limiting | Redis-backed distributed sliding window | In-process `golang.org/x/time/rate` only; Redis imported in `go.mod` but **never instantiated** |
| xDS Streaming | Full SotW ADS with nonce/ACK/NACK | Snapshot builder exists; **no `StreamAggregatedResources` gRPC handler** wired |
| JWT Algorithm | RS256 asymmetric | HS256 symmetric with shared secret |
| mTLS | Envoy↔sidecar mutual TLS | Zero TLS anywhere in the data path |
| Metrics | Prometheus plaintext exposition | Broker and Control Plane `/metrics` return **JSON** — Prometheus will reject |
| IAM | Least-privilege ARN-scoped | Wildcard actions on wildcarded resources |
| CI/CD | Full sidecar build + scan matrix | Sidecars (Rust, Go) **not built or tested** in any CI job |
| Terraform deployment gate | Manual approval before apply | `terraform apply -auto-approve` on every push to `main` |

---

## 3. Security Findings

### SEC-001 — HS256 JWT with Hardcoded Default Secret (CRITICAL)
**File:** `broker/auth.py` lines 32–33; `.env.example` line 48
```
JWT_SECRET = os.environ.get("JWT_SECRET", "change-me-in-production")
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
```
**Risk:** HS256 is a symmetric algorithm. Any party that knows the secret can both verify AND forge tokens. The default `"change-me-in-production"` value is trivially guessable and may be shipped in containers built from unmodified environments. If an attacker obtains the secret (e.g., through a leaked `.env`, CloudWatch logs, or environment variable exposure in ECS), they can mint arbitrary tokens with any `sub` claim.

**Remediation Required:** Migrate to RS256. Signing must use a private key held only by the token issuer; verification uses the public key distributed via JWKS. This eliminates the possibility of token forgery by parties that can only read the public JWKS endpoint.

---

### SEC-002 — Auth Sidecar JWKS Refresh is Non-Functional (CRITICAL)
**File:** `sidecars/auth/src/main.rs` lines 181–185
```rust
async fn refresh_jwks(state: &AppState) -> Result<()> {
    info!("Refreshing JWKS from {}", state.jwks_url);
    // In production: fetch JWKS JSON, parse keys, populate state.jwks_cache
    Ok(())
}
```
**Risk:** The `jwks_cache` (a `DashMap<String, DecodingKey>`) is **never populated**. Every call to `validate_token` iterates over an empty map and falls through to the `Unauthorized` error. This means **the auth sidecar currently rejects 100% of valid tokens.** Additionally, the auth middleware (`auth_middleware`) applies only a path-based bypass for `/health` and `/metrics`, then calls `next.run(request)` for all other paths without any token check. The system is simultaneously blocking all tokens and bypassing auth entirely.

**Remediation Required:** Implement full JWKS fetch loop: HTTP GET to JWKS URI, parse the `keys` array, extract `kid`, `n`, `e` fields, construct `DecodingKey::from_rsa_components()`, store per-KID. Implement KID-based key selection in `validate_token`. Implement auth middleware that enforces token presence for non-exempt paths.

---

### SEC-003 — Rate Limiter Redis Backend Not Connected (CRITICAL)
**File:** `sidecars/ratelimit/go.mod` line 6; `sidecars/ratelimit/main.go` lines 58–100
**Risk:** `go.mod` declares `github.com/go-redis/redis/v8` as a dependency, and the `Config` struct contains `RedisAddr`. However, the `RateLimiter` struct uses only `golang.org/x/time/rate` — a purely in-process token bucket. There is no Redis client instantiation anywhere in `main.go`. This means:
1. Rate limiting state is **per-process and non-distributed** — horizontal scaling provides zero rate-limit isolation.
2. Every Envoy proxy instance that has its own sidecar pod maintains independent counters — a client can bypass the configured RPS by spreading requests across instances.
3. Rate limit state is lost on every pod restart.

This is a silent correctness failure. The service reports healthy, the CI passes, but the core distributed rate-limiting guarantee is absent.

**Remediation Required:** Wire the Redis client in `main.go`. Implement a Lua-based sliding window counter (atomic `EVALSHA` on Redis) for true distributed rate limiting. Add degraded-mode fallback to in-process limiting when Redis is unreachable, with `ratelimit_redis_failures_total` Prometheus counter and configurable fail-closed/open policy.

---

### SEC-004 — gRPC Control Plane Listens on Insecure Port (HIGH)
**File:** `control_plane/main.py` line 65
```python
grpc_server.add_insecure_port(f'[::]:{settings.xds_port}')
```
**Risk:** All xDS configuration pushed to Envoy — including listener definitions, cluster upstreams, and routing rules — travels over an unencrypted, unauthenticated gRPC channel. A network-adjacent attacker could:
1. Intercept configuration pushes and read all routing topology.
2. Inject malicious xDS responses (if they can hijack the TCP stream) to redirect traffic.
3. Subscribe as a fake Envoy node and receive full configuration inventory.

**Remediation Required:** Migrate to `grpc_server.add_secure_port()` with server-side TLS at minimum. For production, enforce mutual TLS between Envoy nodes and the control plane using SPIFFE SVIDs or cert-manager-issued certificates.

---

### SEC-005 — Wildcard IAM Policies (HIGH)
**File:** `terraform/modules/control-plane/main.tf` lines 68–88
```hcl
Action   = ["dynamodb:*"]    Resource = "arn:aws:dynamodb:*:*:table/${var.dynamodb_table}"
Action   = ["sqs:*"]         Resource = "arn:aws:sqs:*:*:${var.sqs_queue_name}"
Action   = ["s3:*"]          Resource = ["arn:aws:s3:::${var.s3_bucket_name}", ...]
Action   = ["route53:*", "cloudfront:*", "elasticloadbalancing:*"]   Resource = "*"
```
**Risk:** `dynamodb:*` includes `dynamodb:DeleteTable`, `dynamodb:RestoreTable`. `s3:*` includes `s3:DeleteBucket`, `s3:PutBucketPolicy` (privilege escalation). `route53:*` with `Resource: "*"` allows modification of any hosted zone in the account. `cloudfront:*` with `Resource: "*"` allows creating/deleting distributions for any domain. These permissions are far beyond what provisioning tasks require and constitute a complete account-level privilege boundary failure.

**Remediation Required:** Scope each action to the minimum required set. Separate `execution role` (pulls secrets, writes logs) from `task role` (calls AWS services). Use exact ARN scoping including account ID and region.

---

### SEC-006 — CloudFront Distribution Uses Default Certificate with Custom Alias (HIGH)
**File:** `worker/provisioners/cdn.py` lines 78–81
```python
"ViewerCertificate": {
    "CloudFrontDefaultCertificate": True,
    "MinimumProtocolVersion": "TLSv1.2_2021",
},
"Aliases": {"Quantity": 1, "Items": [domain]},
```
**Risk:** This configuration is **AWS-rejected at runtime** — CloudFront does not permit custom domain aliases with the default certificate. Attempting to create such a distribution will raise `InvalidViewerCertificate`. Enterprise customers using this plan will experience complete provisioning failure silently masked by a broad `except ClientError: raise`.

**Remediation Required:** Enterprise CDN provisioning must provision an ACM certificate in `us-east-1` for the domain, wait for validation, and reference the certificate ARN in `ViewerCertificate`. Alternatively, accept a pre-validated certificate ARN as a parameter.

---

### SEC-007 — API Key Stored in Plaintext in .env.example (MEDIUM)
**File:** `.env.example` line 38; `broker/auth.py` line 29
```
API_KEY=dev-api-key-change-me
RUVAMCO_API_KEYS = "dev-api-key-change-me"  # default
```
**Risk:** The default API key `"dev-api-key-change-me"` is committed to the repository and used as the production fallback. If no environment variable is set, this key is valid. Container images built from this codebase without explicit environment overrides will accept this key.

---

### SEC-008 — Docker Compose Exposes Credentials in Plaintext (MEDIUM)
**File:** `docker-compose.yml` lines 32–33, 125
```yaml
MINIO_ROOT_USER: minioadmin
MINIO_ROOT_PASSWORD: minioadmin
GF_SECURITY_ADMIN_PASSWORD: admin
```
**Risk:** While these are local dev credentials, they establish a pattern that can leak into staging environments. There is no `.env` injection pattern demonstrated for docker-compose secrets. The `AWS_ACCESS_KEY_ID: test` / `AWS_SECRET_ACCESS_KEY: test` pattern is correct for LocalStack/ElasticMQ but must be explicitly gated.

---

### SEC-009 — No CORS Restriction in Production (MEDIUM)
**File:** `broker/models.py` line 77
```python
allow_origins: List[str] = ["*"]
```
**Risk:** The default CORS configuration allows requests from any origin. For a Service Broker API handling provisioning operations, this should be restricted to known internal origins or disabled entirely (broker APIs should be internal-only).

---

## 4. Runtime Stability Findings

### RT-001 — Prometheus /metrics Endpoints Return JSON (BLOCKER)
**Files:** `broker/main.py` lines 197–204; `control_plane/main.py` lines 149–157
```python
@app.get("/metrics")
async def metrics():
    return {   # FastAPI auto-serializes to JSON
        "provisioning_requests_total": 0,
        ...
    }
```
**Risk:** Prometheus scraper expects `text/plain; version=0.0.4` exposition format (e.g., `# HELP`, `# TYPE`, `metric_name value`). These endpoints return `application/json`. Prometheus will raise a parse error and discard all metrics. The monitoring stack is entirely non-functional for broker and control-plane services.

---

### RT-002 — xDS ADS StreamAggregatedResources Not Wired (BLOCKER)
**File:** `control_plane/xds_server.py`; `control_plane/main.py` lines 55–69
**Risk:** `AggregatedDiscoveryService` has `build_snapshot()` and `build_all_snapshots()` methods but **does not implement `StreamAggregatedResources`** — the bidirectional gRPC streaming method that Envoy calls. The gRPC servicer is registered:
```python
envoy_service_discovery_pb2_grpc.add_AggregatedDiscoveryServiceServicer_to_server(ads_service, grpc_server)
```
But without the streaming handler, Envoy receives `UNIMPLEMENTED` for any xDS subscription. **No dynamic configuration can be delivered to any Envoy node.**

---

### RT-003 — xDS Nonce, ACK/NACK, and Version Tracking Absent (HIGH)
**File:** `control_plane/xds_server.py` lines 32–56
**Risk:** The xDS SotW protocol requires:
- Server assigns a `nonce` to each response
- Client ACKs by echoing the nonce with the received `version_info`
- Client NACKs by echoing the nonce with the *previous* `version_info` and an `error_detail`

The current implementation uses a simple `sha256` hash for versioning but has no nonce generation, no ACK/NACK handling, and no per-node subscription tracking. Without this, the control plane cannot determine if Envoy has successfully applied a configuration or is stuck in a NACK loop. Configuration drift is undetectable.

---

### RT-004 — Worker Hardcodes SQS URL and DynamoDB Table (HIGH)
**File:** `worker/main.py` lines 33–34
```python
self.queue_url = "https://sqs.us-east-1.amazonaws.com/account/ruvamco-tasks"
self.control_plane_url = "http://control-plane:8080"
```
And lines 173–174 (called on every state update):
```python
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('ruvamco-instances')
```
**Risk:** The literal string `"account"` in the SQS URL is a placeholder, not a real AWS account ID. This will fail with `AWS.SimpleQueueService.NonExistentQueue` at runtime. The `boto3.resource('dynamodb')` call inside `mark_active/mark_failed/mark_deleted` ignores `DYNAMODB_ENDPOINT` — meaning local development with ElasticMQ will fail on every state transition.

---

### RT-005 — Control Plane Uses Deprecated on_event Lifecycle (LOW)
**File:** `control_plane/main.py` line 45
```python
@app.on_event("startup")
```
**Risk:** `@app.on_event` is deprecated in FastAPI 0.93+. The lifespan context manager pattern (`@asynccontextmanager lifespan`) is the correct approach. The broker correctly uses `lifespan` — the control plane should be aligned.

---

### RT-006 — Broker Settings Ignore Endpoint Environment Variables (HIGH)
**File:** `broker/main.py` lines 28–38
```python
class Settings(BaseModel):
    sqs_queue_url: str = "https://sqs.us-east-1.amazonaws.com/account/ruvamco-tasks"

settings = Settings()
db = DatabaseManager(settings.dynamodb_table, settings.region)    # no endpoint_url
queue = QueueManager(settings.sqs_queue_url, settings.region)     # no endpoint_url
```
**Risk:** `DatabaseManager.__init__` accepts `endpoint_url` but it is not passed. `QueueManager.__init__` accepts `endpoint_url` but it is not passed. The `SQS_ENDPOINT` and `DYNAMODB_ENDPOINT` environment variables defined in `docker-compose.yml` are silently ignored by the broker.

---

### RT-007 — DynamoDB Full Table Scan in Hot Path (MEDIUM)
**Files:** `broker/database.py` lines 104–121; `control_plane/context_manager.py` lines 95–115
**Risk:** `get_all_instances()` performs a full `Table.scan()` with a filter expression. DynamoDB `scan` reads every item in the table and then applies the filter — cost and latency scale linearly with table size. At 10,000 instances, this is prohibitive. The `/metrics` endpoint in the control plane calls `get_all_instances()` on every scrape. Prometheus scrapes every 15 seconds by default.

---

## 5. Infrastructure Findings

### INF-001 — DNS Provisioner Uses Placeholder Hosted Zone ID (HIGH)
**File:** `worker/provisioners/dns.py` line 20
```python
DEFAULT_HOSTED_ZONE_ID = "Z0000000000000"
```
**Risk:** The placeholder zone ID `"Z0000000000000"` does not exist. Every DNS provisioning call will raise `NoSuchHostedZone`. This is a silent failure — DNS records are never created, but instances may be marked active.

---

### INF-002 — Terraform Backend Hardcodes Region and Account Resources (MEDIUM)
**File:** `terraform/main.tf` lines 22–28
```hcl
backend "s3" {
    bucket         = "ruvamco-terraform-state"
    region         = "us-east-1"
```
**Risk:** The S3 backend bucket, key, and DynamoDB lock table are hardcoded strings. For multi-region or multi-account deployments, this creates state collision risks and makes environment promotion (dev → staging → production) error-prone.

---

### INF-003 — No SQS KMS Encryption or Queue Policy (MEDIUM)
**File:** `terraform/main.tf` lines 105–128
**Risk:** The SQS queue has no `kms_master_key_id` (server-side encryption disabled) and no resource-based queue policy restricting which principals can send/receive messages. Any IAM entity in the account with `sqs:SendMessage` can inject arbitrary provisioning tasks.

---

### INF-004 — S3 Context Bucket Uses AES256 Not KMS (LOW)
**File:** `terraform/main.tf` lines 145–152
**Risk:** AES256 (S3-SSE) is acceptable but does not provide key rotation, CloudTrail-level access logging per key, or the audit trail required for compliance frameworks (SOC 2, HIPAA). KMS with customer-managed keys (CMK) is required for enterprise-grade deployments.

---

### INF-005 — Proxy Fleet Module Not Reviewed (BLOCKER)
**File:** `terraform/modules/proxy-fleet/` (not inspectable — assumed similar patterns)
**Risk:** The EC2 Auto Scaling Group for Envoy proxies likely has the same IAM over-permission patterns. The proxy AMI ID is an empty string default — attempting `terraform apply` without providing `proxy_ami_id` will fail or use an unintended image.

---

## 6. Observability Findings

### OBS-001 — No /health/live or /health/ready Split (HIGH)
**All services** expose only `/health`. Kubernetes liveness and readiness probes require distinct endpoints:
- **Liveness** (`/health/live`): Is the process alive? Only fails for deadlocks / OOM.
- **Readiness** (`/health/ready`): Is the service ready to accept traffic? Fails until DynamoDB/SQS connections are verified.

Without this split, Kubernetes restarts healthy-but-warming pods and routes traffic to pods that haven't finished connecting to dependencies.

---

### OBS-002 — Observability Sidecar Hardcodes instance_id (MEDIUM)
**File:** `sidecars/observability/main.py` line 127
```python
ACTIVE_CONNECTIONS.labels(instance_id="local").set(value)
```
**Risk:** All instances report metrics under the label `instance_id="local"`, making per-instance attribution impossible.

---

### OBS-003 — No Structured Logging or Correlation IDs (MEDIUM)
**All services** use `logging.basicConfig(level=logging.INFO)` with unstructured format strings. There are no request IDs, trace IDs, or instance IDs injected into log records. Debugging production issues across broker → SQS → worker → control plane → Envoy is impossible without correlation.

---

### OBS-004 — Jaeger Configured but No OpenTelemetry SDK Initialized (LOW)
**File:** `docker-compose.yml` lines 129–135; `.env.example` line 44
`OTEL_EXPORTER_OTLP_ENDPOINT` is defined, but no service initializes an OpenTelemetry SDK, creates a tracer provider, or instruments HTTP/gRPC calls. Jaeger receives no data.

---

## 7. CI/CD Findings

### CICD-001 — Sidecar Components Absent from Build Matrix (CRITICAL)
**File:** `.github/workflows/ci.yml` line 20
```yaml
matrix:
    component: [broker, worker, control_plane, cli]
```
The Rust auth sidecar and Go rate-limit sidecar are **never built, tested, or linted** in CI. A broken Rust compilation or Go vet failure would be invisible until deployment. Neither `cargo build`, `cargo test`, `cargo audit`, nor `go build`, `go vet`, `govulncheck` are run.

---

### CICD-002 — terraform apply -auto-approve on Every Main Push (CRITICAL)
**File:** `.github/workflows/ci.yml` lines 132–133
```yaml
- name: Terraform Apply
  run: cd terraform && terraform apply -auto-approve
```
**Risk:** Every merge to `main` automatically applies infrastructure changes to production without human review. A misconfigured security group rule, IAM policy, or routing change is applied instantly. This violates GitOps principles and is incompatible with any change management process.

---

### CICD-003 — Long-Term AWS Credentials in CI (HIGH)
**File:** `.github/workflows/ci.yml` lines 117–118
```yaml
aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
```
**Risk:** Long-term IAM user credentials stored as GitHub secrets are a persistent credential leak risk. If the repository is compromised, the credentials remain valid until manually rotated. AWS and GitHub both recommend OpenID Connect (OIDC) federation for CI/CD authentication.

---

### CICD-004 — No Container Image Scanning (HIGH)
No `trivy`, `grype`, or `docker scout` scan is run on any built image. CVEs in base images (Python 3.11, Rust, Go 1.21, `envoyproxy/envoy`) are never detected.

---

### CICD-005 — No Infrastructure Security Scanning (HIGH)
No `tfsec`, `checkov`, or `terrascan` is run against the Terraform configuration. The wildcard IAM policies (SEC-005) would be caught immediately by any of these tools.

---

### CICD-006 — Docker Images Tagged with :latest (MEDIUM)
**File:** `.github/workflows/ci.yml` lines 83, 90, 97, 104
```yaml
tags: ruvamco/broker:latest,ruvamco/broker:${{ github.sha }}
```
Publishing `:latest` from CI is an anti-pattern in production. Kubernetes clusters pinned to `:latest` will pull different images at different times depending on node image cache state. All production deployments must reference immutable SHA-pinned tags.

---

## 8. Proposed Remediation Architecture

### 8.1 Authentication Architecture (Target)

```
Token Issuance (external IdP OR ruvamco-issuer service):
  - RSA-4096 private key stored in AWS KMS or HashiCorp Vault
  - Sign tokens with RS256 algorithm
  - Expose public keys at /.well-known/jwks.json
  - Each key has a unique kid (key ID)

Envoy JWT Filter (per listener):
  - envoy.filters.http.jwt_authn
  - remote_jwks with 5-minute cache TTL
  - Validates iss, aud, exp, kid

Auth Sidecar (Rust):
  - Fetches JWKS on startup + every 5 minutes
  - Stores DecodingKey per kid in DashMap
  - On validation: selects key by kid from JWT header
  - On NACK: returns 401 with WWW-Authenticate header
  - Exposes ruvamco_auth_requests_total{result="ok|invalid|expired|missing"} counter
```

### 8.2 mTLS Architecture (Target)

**Short-term (self-signed, local CA):**
```
cert-manager (Kubernetes) OR cfssl (standalone):
  - Root CA: ruvamco-root-ca (offline, stored in HSM/KMS)
  - Intermediate CA: ruvamco-infra-ca (online, 90-day rotation)
  - Leaf certs: per-service, 24-hour TTL, auto-rotated

Envoy ↔ Auth Sidecar:     mutual TLS on port 8081
Envoy ↔ Ratelimit Sidecar: mutual TLS on port 8082
Envoy ↔ Control Plane:     mutual TLS on port 18000 (gRPC)
```

**Long-term (production SPIFFE):**
```
SPIRE Server: issues SVIDs to workloads via Kubernetes attestor
SPIRE Agent: runs as DaemonSet, attests pod identity via SA tokens
Envoy SDS: fetches mTLS certs from SPIRE Agent via /tmp/spire-agent/public/api.sock
```

### 8.3 xDS ADS Architecture (Target)

```
Envoy Node → gRPC bidi stream → StreamAggregatedResources
                                        ↓
                              DiscoveryRequest received:
                              {
                                node: { id: "instance-abc", cluster: "ruvamco" },
                                type_url: "type.googleapis.com/envoy.config.listener.v3.Listener",
                                version_info: "",   # empty = first request
                                nonce: ""
                              }
                                        ↓
                              Control Plane builds snapshot:
                              {version: "sha256[:16]", nonce: "uuid4()"}
                                        ↓
                              DiscoveryResponse sent to Envoy
                                        ↓
                              Envoy applies config, sends ACK:
                              {version_info: "sha256[:16]", nonce: "uuid4()"}
                                        ↓
                              On NACK: version_info = previous, error_detail set
                              Control Plane logs NACK, retains previous snapshot
```

Key implementation requirements:
- `nonce` must be unique per response (UUID4)
- `version_info` must be monotonically increasing (content hash or sequence number)
- Per-node subscription state tracked in memory (or Redis for HA)
- Resource type grouping: LDS, CDS, RDS, EDS in correct dependency order
- Snapshot cache: `envoy-go-control-plane` `cache.SnapshotCache` is the reference implementation pattern

### 8.4 Rate Limiting Architecture (Target)

```
Redis Cluster (3 shards, 3 replicas):
  └── Sliding window Lua script:
      KEYS[1] = "ratelimit:{key}"
      ARGV[1] = window_ms, ARGV[2] = limit, ARGV[3] = now_ms

Rate Limit Sidecar:
  - Primary path: EVALSHA → Redis (< 2ms p99)
  - Degraded mode (Redis unreachable after 2 consecutive failures):
    - Fall back to in-process golang.org/x/time/rate
    - Reduce threshold to 50% of configured limit (conservative)
    - Expose ratelimit_redis_failures_total counter
    - Expose ratelimit_degraded_mode gauge (0/1)
  - fail-closed mode (RATELIMIT_FAIL_CLOSED=true):
    - On Redis failure, reject ALL requests (deny-by-default)
    - Used for enterprise/high-security tenants

Envoy ext_ratelimit filter:
  - Calls rate limit sidecar via HTTP (or gRPC for Envoy rate limit service protocol)
  - On 429: pass through Retry-After header
  - On sidecar timeout: configurable (pass/fail)
```

### 8.5 Observability Architecture (Target)

```
Per-service:
  - /health/live    → liveness probe (process alive)
  - /health/ready   → readiness probe (dependencies connected)
  - /metrics        → Prometheus text exposition (prometheus_client)

Broker metrics:
  ruvamco_broker_provisioning_requests_total{plan, status}
  ruvamco_broker_provisioning_duration_seconds{plan} (histogram)
  ruvamco_broker_active_instances (gauge, DynamoDB-backed)

Control Plane metrics:
  ruvamco_cp_xds_snapshots_total{instance_id}
  ruvamco_cp_xds_nacks_total{instance_id}
  ruvamco_cp_cache_size (gauge)
  ruvamco_cp_config_generations_total (counter)

Auth Sidecar metrics:
  ruvamco_auth_requests_total{result="ok|invalid|expired|missing"}
  ruvamco_auth_jwks_refresh_total{status="ok|error"}
  ruvamco_auth_jwks_cache_size (gauge)

Rate Limit Sidecar metrics:
  ruvamco_ratelimit_checks_total{result="allowed|denied"}
  ruvamco_ratelimit_redis_failures_total
  ruvamco_ratelimit_degraded_mode (gauge 0/1)
  ruvamco_ratelimit_active_keys (gauge)

Future (Phase 6):
  OpenTelemetry traces with W3C trace-context propagation
  Correlation ID injection via X-Request-ID header
  Structured JSON logging with trace_id field
```

---

## 9. Phased Remediation Strategy

### Phase 1 — Runtime & Configuration Stabilization
**Duration Estimate:** 1 week  
**Blocker for:** Everything downstream  
**Risk if skipped:** Local development environment non-functional; metrics dark

| Task | File(s) | Priority |
|---|---|---|
| Fix broker Settings to read `DYNAMODB_ENDPOINT`, `SQS_ENDPOINT` from env | `broker/main.py` | P0 |
| Pass endpoint URLs to DatabaseManager and QueueManager constructors | `broker/main.py` | P0 |
| Fix worker to read queue URL, table name, control plane URL from env | `worker/main.py` | P0 |
| Fix worker mark_active/failed/deleted to use env-injected DynamoDB endpoint | `worker/main.py` | P0 |
| Replace broker `/metrics` JSON with `prometheus_client generate_latest` | `broker/main.py` | P0 |
| Replace control plane `/metrics` JSON with `prometheus_client generate_latest` | `control_plane/main.py` | P0 |
| Add `/health/live` and `/health/ready` to all Python services | all services | P1 |
| Migrate control plane from `@app.on_event` to `lifespan` | `control_plane/main.py` | P1 |
| Add `DNS_HOSTED_ZONE_ID` env var to DNSProvisioner | `worker/provisioners/dns.py` | P0 |
| Import fix for `generated` protobuf module (conditional import) | `control_plane/main.py` | P0 |

---

### Phase 2 — Control Plane Protocol Correctness
**Duration Estimate:** 2 weeks  
**Blocker for:** Any dynamic Envoy configuration delivery  
**Risk if skipped:** Envoy fleet cannot receive configuration — static bootstrap only

| Task | File(s) | Priority |
|---|---|---|
| Implement `StreamAggregatedResources` gRPC handler | `control_plane/xds_server.py` | P0 |
| Implement nonce generation (UUID4) per response | `control_plane/xds_server.py` | P0 |
| Implement ACK/NACK detection and logging | `control_plane/xds_server.py` | P0 |
| Implement per-node subscription state tracking | `control_plane/xds_server.py` | P0 |
| Implement snapshot versioning with monotonic counter | `control_plane/xds_server.py` | P0 |
| Implement push-on-change (notify connected nodes on reload) | `control_plane/xds_server.py` | P1 |
| Add resource type ordering: LDS → CDS → RDS → EDS | `control_plane/xds_server.py` | P1 |
| Generate correct protobuf bindings (`envoy-go-control-plane` reference) | `control_plane/generated/` | P0 |
| Add xDS metrics: snapshots_built_total, nacks_total, connected_nodes gauge | `control_plane/xds_server.py` | P1 |
| Write Envoy static bootstrap YAML pointing to xDS server | `envoy-bootstrap.yaml` | P0 |

---

### Phase 3 — Security Architecture Enforcement
**Duration Estimate:** 3 weeks  
**Blocker for:** Any external traffic or production customer data  
**Risk if skipped:** All traffic is unprotected; tokens are forgeable

| Task | File(s) | Priority |
|---|---|---|
| Generate RSA-4096 keypair for JWT signing | Key management | P0 |
| Implement JWKS endpoint serving public key(s) with kid | Broker or dedicated issuer | P0 |
| Migrate `broker/auth.py` from HS256 to RS256 | `broker/auth.py` | P0 |
| Remove `JWT_SECRET` and `JWT_ALGORITHM` from `.env.example` | `.env.example` | P0 |
| Add `JWKS_URL`, `JWT_PRIVATE_KEY_ARN` to env schema | `.env.example` | P0 |
| Implement full JWKS HTTP fetch in auth sidecar | `sidecars/auth/src/main.rs` | P0 |
| Implement KID-based key selection in `validate_token` | `sidecars/auth/src/main.rs` | P0 |
| Implement enforcing `auth_middleware` (not pass-through) | `sidecars/auth/src/main.rs` | P0 |
| Wire Redis client in rate limit sidecar | `sidecars/ratelimit/main.go` | P0 |
| Implement Lua sliding window script execution via Redis | `sidecars/ratelimit/main.go` | P0 |
| Implement degraded-mode fallback with reduced thresholds | `sidecars/ratelimit/main.go` | P0 |
| Add `ratelimit_redis_failures_total` counter | `sidecars/ratelimit/main.go` | P0 |
| Add `ext_authz` filter to listener.j2 pointing to auth sidecar | `control_plane/templates/listener.j2` | P0 |
| Add `envoy.filters.http.ratelimit` filter to listener.j2 | `control_plane/templates/listener.j2` | P0 |
| Add upstream TLS context to cluster.j2 | `control_plane/templates/cluster.j2` | P1 |
| Generate local CA + leaf certs for dev mTLS | `scripts/gen-certs.sh` | P1 |
| Configure control plane gRPC with TLS | `control_plane/main.py` | P0 |
| Fix CloudFront distribution to use ACM certificate | `worker/provisioners/cdn.py` | P0 |

---

### Phase 4 — Infrastructure Hardening
**Duration Estimate:** 1 week  
**Blocker for:** Production AWS deployment  
**Risk if skipped:** Privilege escalation, data breach via overpermissioned roles

| Task | File(s) | Priority |
|---|---|---|
| Replace `dynamodb:*` with minimum action set | `terraform/modules/control-plane/main.tf` | P0 |
| Replace `sqs:*` with minimum action set | `terraform/modules/control-plane/main.tf` | P0 |
| Replace `s3:*` with minimum action set | `terraform/modules/control-plane/main.tf` | P0 |
| Restrict `route53` to specific hosted zone ARN | `terraform/modules/control-plane/main.tf` | P0 |
| Restrict `cloudfront` to distribution-level ARNs | `terraform/modules/control-plane/main.tf` | P0 |
| Add account ID interpolation to all resource ARNs | `terraform/modules/control-plane/main.tf` | P0 |
| Add `DNS_HOSTED_ZONE_ID` to Terraform outputs + ECS env | terraform + ECS task | P0 |
| Enable SQS KMS encryption | `terraform/main.tf` | P1 |
| Add SQS queue resource policy | `terraform/main.tf` | P1 |
| Migrate S3 SSE from AES256 to KMS CMK | `terraform/main.tf` | P1 |
| Add S3 public access block | `terraform/main.tf` | P0 |
| Add `proxy_ami_id` validation (non-empty) | `terraform/variables.tf` | P1 |
| Enable DynamoDB deletion protection | `terraform/main.tf` | P1 |

---

### Phase 5 — CI/CD & Delivery Hardening
**Duration Estimate:** 1 week  
**Blocker for:** Safe automated delivery  
**Risk if skipped:** Broken sidecars ship silently; production infra auto-applied without approval

| Task | File(s) | Priority |
|---|---|---|
| Add Rust build + test job for auth sidecar | `.github/workflows/ci.yml` | P0 |
| Add Go build + vet + test job for ratelimit sidecar | `.github/workflows/ci.yml` | P0 |
| Add `cargo audit` to Rust CI job | `.github/workflows/ci.yml` | P0 |
| Add `govulncheck` to Go CI job | `.github/workflows/ci.yml` | P0 |
| Add `tfsec` or `checkov` scan to Terraform job | `.github/workflows/ci.yml` | P0 |
| Add `trivy` image scan to build job | `.github/workflows/ci.yml` | P0 |
| Remove `terraform apply -auto-approve` from CI | `.github/workflows/ci.yml` | P0 |
| Add manual approval gate before Terraform apply | `.github/workflows/ci.yml` | P0 |
| Migrate AWS auth to OIDC (aws-actions/configure-aws-credentials@v4 with role-to-assume) | `.github/workflows/ci.yml` | P0 |
| Build + push sidecar images (auth, ratelimit, observability) | `.github/workflows/ci.yml` | P0 |
| Pin all `:latest` image tags to SHA-pinned or semver | docker-compose + CI | P1 |
| Add `RUVAMCO_API_KEYS` to GitHub Actions secrets | CI secrets | P0 |

---

### Phase 6 — Future Production Hardening Roadmap
**Duration Estimate:** Ongoing (3–6 months post-Phase 5)  
**Not a blocker for launch, but required for enterprise SLA**

| Initiative | Description |
|---|---|
| OpenTelemetry | Instrument all services with OTLP exporter; deploy OTel Collector; ship traces to Jaeger/Tempo |
| SPIFFE/SPIRE | Replace self-signed mTLS with SPIRE-issued SVIDs; zero-touch cert rotation |
| Adaptive Rate Limiting | Machine-learning based threshold adjustment based on traffic patterns |
| Delta xDS (incremental) | Migrate from SotW ADS to Delta xDS for large fleets (10,000+ Envoy nodes) |
| Multi-region xDS federation | Regional control planes with global state replication via DynamoDB Global Tables |
| Envoy WASM extensions | Replace ext_authz HTTP call with WASM-based inline auth for sub-millisecond overhead |
| Advanced rollout controls | Canary deployments via xDS weighted clusters; progressive rollout with automatic rollback on NACK rate spike |
| Secrets Manager integration | Replace env-var secrets with AWS Secrets Manager + IAM role injection |

---

## 10. Risk Assessment

See `risk_register.md` for full risk matrix.

**Critical risks (must resolve before GA):**
1. JWKS stub → auth sidecar accepts no valid tokens (or bypasses auth entirely)
2. Redis absent → rate limiting non-distributed, bypassable
3. xDS ADS not wired → no dynamic configuration delivery
4. HS256 → JWT forgery possible
5. Wildcard IAM → complete account-level privilege escalation path
6. auto-approve Terraform → unreviewed infrastructure changes in production

---

## 11. Verification Strategy

### Phase 1 Verification
- `docker-compose up` starts cleanly with all services healthy
- `curl localhost:8080/metrics` returns `text/plain` Prometheus format
- `curl localhost:8081/metrics` returns `text/plain` Prometheus format  
- Worker processes a test SQS message and updates DynamoDB status
- Prometheus UI shows all 4 scrape targets as UP

### Phase 2 Verification
- Envoy connects to xDS server and receives LDS/CDS/RDS resources
- Envoy admin `/config_dump` shows dynamically received configuration
- Modifying S3 context and calling `/v1/reload` results in Envoy picking up new config within 5 seconds
- Control plane logs show ACK receipt for each delivered snapshot
- Deliberately malformed config results in logged NACK

### Phase 3 Verification
- `curl -H "Authorization: Bearer <hs256_token>" /auth/validate` returns 401
- `curl -H "Authorization: Bearer <rs256_token>" /auth/validate` returns 200
- Rate limit sidecar under 200 RPS burst test: Redis `MONITOR` shows sliding window keys
- Killing Redis: sidecar switches to degraded mode within 5 seconds; `ratelimit_degraded_mode` gauge == 1
- Envoy forwards 401 to client when auth sidecar rejects token
- `nmap --script ssl-enum-ciphers localhost:18000` shows TLS 1.3

### Phase 4 Verification
- `aws iam simulate-principal-policy` confirms ECS task role cannot call `dynamodb:DeleteTable`
- `tfsec ./terraform` returns zero HIGH/CRITICAL findings
- `checkov -d ./terraform` returns passing

### Phase 5 Verification
- CI pipeline on a PR runs Rust/Go builds successfully
- `cargo audit` returns no known vulnerabilities
- `govulncheck ./...` returns clean
- `trivy image ruvamco/broker:sha` returns no CRITICAL CVEs
- Merging to main does NOT automatically run `terraform apply`
- AWS credentials in CI are obtained via OIDC (no stored long-term keys)

---

## 12. Production Readiness Definition

See `production_readiness_definition.md` for the complete checklist.

**Gate criteria for GA:**
- All Phase 1–5 items complete and verified
- Zero CRITICAL or HIGH security findings from automated scans
- Prometheus scraping all 5 service targets
- Envoy fleet receiving dynamic configuration via xDS
- All JWT tokens signed with RS256
- mTLS enforced on all internal communication paths
- IAM policies passing tfsec with zero HIGH findings
- CI pipeline requiring human approval before Terraform apply
- All sidecar Docker images built and scanned in CI

---

## 13. Future Hardening Roadmap

Refer to Phase 6 in Section 9. Priority order for post-GA hardening:

1. **OpenTelemetry** — observability completeness
2. **SPIFFE/SPIRE** — zero-trust identity
3. **Delta xDS** — fleet scalability beyond 1,000 nodes
4. **Multi-region** — HA and latency requirements
5. **WASM extensions** — performance optimization
6. **Adaptive rate limiting** — intelligence layer

---

*This document constitutes the authoritative remediation plan for RUVAMCO v1.0 → v2.0 production hardening. All sections are for planning purposes only. No code has been modified as part of this review.*

*Meer Corporation — Confidential — Not for external distribution*
