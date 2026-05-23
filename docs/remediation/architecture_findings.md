# RUVAMCO — Architecture Findings Report
**Meer Corporation — Confidential**
**Date: 2026-05-23 | Classification: Internal Architecture Review**

---

## Document Purpose

This document catalogs every architectural finding identified during the end-to-end audit of the RUVAMCO platform. Each finding includes severity, affected components, root cause, impact, and recommended remediation. Findings are cross-referenced to the implementation plan phases.

---

## Severity Scale

| Severity | Definition |
|---|---|
| **CRITICAL** | Exploitable vulnerability or complete functional failure. Blocks production. |
| **HIGH** | Significant security or reliability risk. Must resolve before GA. |
| **MEDIUM** | Correctness issue or anti-pattern. Should resolve before GA. |
| **LOW** | Technical debt or best-practice deviation. Resolve post-GA. |

---

## Domain 1: Authentication & Identity

### FINDING AUTH-001: HS256 Symmetric JWT (CRITICAL)
- **Files:** [auth.py](file:///c:/Users/hashm/Desktop/Projects/RUVAMCO/broker/auth.py#L32-L33), [.env.example](file:///c:/Users/hashm/Desktop/Projects/RUVAMCO/.env.example#L47-L48)
- **Root Cause:** JWT signing uses `HS256` algorithm with a shared secret. The secret has a hardcoded fallback `"change-me-in-production"`.
- **Impact:** Any entity with the secret (leaked env, container introspection, log exposure) can forge arbitrary tokens. HS256 fundamentally cannot distinguish signers from verifiers.
- **Remediation:** Phase 3 — Migrate to RS256 with keypair. Private key in KMS/Vault, public key via JWKS endpoint.
- **Remediation Phase:** 3

### FINDING AUTH-002: JWKS Refresh Stub (CRITICAL)
- **Files:** [main.rs](file:///c:/Users/hashm/Desktop/Projects/RUVAMCO/sidecars/auth/src/main.rs#L181-L185)
- **Root Cause:** `refresh_jwks()` is a no-op that returns `Ok(())`. The `jwks_cache` DashMap is never populated.
- **Impact:** Auth sidecar's `validate_token()` iterates an empty cache, rejects 100% of valid tokens. Simultaneously, `auth_middleware()` is pass-through for non-health paths, meaning no auth is enforced.
- **Remediation:** Phase 3 — Full JWKS fetch implementation with JWK parsing and KID-based key storage.
- **Remediation Phase:** 3

### FINDING AUTH-003: Auth Middleware is Pass-Through (HIGH)
- **Files:** [main.rs](file:///c:/Users/hashm/Desktop/Projects/RUVAMCO/sidecars/auth/src/main.rs#L157-L169)
- **Root Cause:** `auth_middleware` exempts `/health` and `/metrics`, then calls `next.run(request)` for all other paths without any token extraction or validation.
- **Impact:** Every request that reaches the auth sidecar (except `/auth/validate` which is a separate handler) passes through unauthenticated.
- **Remediation:** Phase 3 — Enforce token presence in middleware; return 401 on missing/invalid tokens.
- **Remediation Phase:** 3

### FINDING AUTH-004: Default API Key in Source Control (MEDIUM)
- **Files:** [auth.py](file:///c:/Users/hashm/Desktop/Projects/RUVAMCO/broker/auth.py#L28-L29), [.env.example](file:///c:/Users/hashm/Desktop/Projects/RUVAMCO/.env.example#L38)
- **Root Cause:** `RUVAMCO_API_KEYS` defaults to `"dev-api-key-change-me"`. This value is committed to git and is the effective key if no environment override is set.
- **Impact:** Containers built without explicit key override accept the default key.
- **Remediation:** Phase 3 — Remove default; require explicit key configuration; fail loudly on startup if not set.
- **Remediation Phase:** 3

---

## Domain 2: xDS Control Plane

### FINDING XDS-001: StreamAggregatedResources Not Implemented (CRITICAL)
- **Files:** [xds_server.py](file:///c:/Users/hashm/Desktop/Projects/RUVAMCO/control_plane/xds_server.py), [main.py](file:///c:/Users/hashm/Desktop/Projects/RUVAMCO/control_plane/main.py#L55-L69)
- **Root Cause:** `AggregatedDiscoveryService` class provides `build_snapshot()` and version management but does not define the `StreamAggregatedResources` method that Envoy calls. The servicer is registered on the gRPC server, so Envoy connections arrive but receive `UNIMPLEMENTED`.
- **Impact:** No Envoy proxy can receive dynamic configuration. The entire xDS pipeline is non-functional.
- **Remediation:** Phase 2 — Implement full bidirectional streaming handler.
- **Remediation Phase:** 2

### FINDING XDS-002: No Nonce or ACK/NACK Handling (HIGH)
- **Files:** [xds_server.py](file:///c:/Users/hashm/Desktop/Projects/RUVAMCO/control_plane/xds_server.py#L32-L56)
- **Root Cause:** Snapshot versioning uses `sha256[:16]` content hash but there is no nonce generation, no ACK/NACK response parsing, and no per-node subscription tracking.
- **Impact:** Even if streaming were implemented, the control plane could not detect whether Envoy accepted or rejected a configuration. Configuration drift is undetectable; NACK loops would go unnoticed.
- **Remediation:** Phase 2 — Implement nonce (UUID4), ACK detection (version match), NACK detection (version mismatch with error_detail).
- **Remediation Phase:** 2

### FINDING XDS-003: Generated Protobuf Stubs Missing (HIGH)
- **Files:** [main.py](file:///c:/Users/hashm/Desktop/Projects/RUVAMCO/control_plane/main.py#L60)
- **Root Cause:** `from .generated import envoy_service_discovery_pb2_grpc` references a `generated` package that does not exist in the repository. No proto compilation script exists.
- **Impact:** Import fails at runtime, preventing the control plane from starting the gRPC server.
- **Remediation:** Phase 2 — Create proto generation script; generate stubs.
- **Remediation Phase:** 2

### FINDING XDS-004: gRPC Server Uses Insecure Port (HIGH)
- **Files:** [main.py](file:///c:/Users/hashm/Desktop/Projects/RUVAMCO/control_plane/main.py#L65)
- **Root Cause:** `grpc_server.add_insecure_port()` is called. No TLS credentials are configured.
- **Impact:** xDS configuration (entire routing topology, upstream addresses, auth settings) transmitted in cleartext. Network-adjacent attacker can intercept or inject.
- **Remediation:** Phase 3 — Migrate to `add_secure_port()` with TLS; Phase 6 — mTLS via SPIFFE.
- **Remediation Phase:** 3

### FINDING XDS-005: No Resource Type Ordering (MEDIUM)
- **Files:** [xds_server.py](file:///c:/Users/hashm/Desktop/Projects/RUVAMCO/control_plane/xds_server.py#L41-L45)
- **Root Cause:** Snapshot contains listeners, clusters, routes as unordered dict. Envoy ADS requires specific ordering: CDS → EDS → LDS → RDS to avoid dangling references.
- **Impact:** Envoy may NACK listener configurations that reference not-yet-delivered clusters.
- **Remediation:** Phase 2 — Enforce resource type ordering.
- **Remediation Phase:** 2

---

## Domain 3: Rate Limiting

### FINDING RL-001: Redis Not Connected (CRITICAL)
- **Files:** [main.go](file:///c:/Users/hashm/Desktop/Projects/RUVAMCO/sidecars/ratelimit/main.go#L58-L100), [go.mod](file:///c:/Users/hashm/Desktop/Projects/RUVAMCO/sidecars/ratelimit/go.mod#L6)
- **Root Cause:** `go.mod` declares `go-redis/redis/v8` dependency. Config struct has `RedisAddr`. But `RateLimiter` struct only uses `golang.org/x/time/rate` (in-process). No Redis client is ever instantiated.
- **Impact:** Rate limiting is per-process, non-distributed. Horizontal scaling provides zero isolation — clients can bypass limits by distributing requests across pods.
- **Remediation:** Phase 3 — Wire Redis client, implement distributed sliding window.
- **Remediation Phase:** 3

### FINDING RL-002: No Degraded Mode (HIGH)
- **Files:** [main.go](file:///c:/Users/hashm/Desktop/Projects/RUVAMCO/sidecars/ratelimit/main.go)
- **Root Cause:** No fallback behavior is defined for when Redis is unreachable.
- **Impact:** Once Redis integration is added, Redis downtime will cause either hard failures (500s) or silent open-pass (no limiting). Neither is acceptable.
- **Remediation:** Phase 3 — Implement degraded mode with reduced thresholds and failure metrics.
- **Remediation Phase:** 3

### FINDING RL-003: No Rate Limit Filter in Envoy (HIGH)
- **Files:** [listener.j2](file:///c:/Users/hashm/Desktop/Projects/RUVAMCO/control_plane/templates/listener.j2)
- **Root Cause:** The listener template contains `jwt_authn` filter (conditionally) and `router` filter, but no `ext_ratelimit` or `ext_authz` filter is defined. The rate limit sidecar is never called by Envoy.
- **Impact:** Even if the rate limit sidecar is functioning perfectly, Envoy never consults it. Rate limiting is entirely bypassed at the proxy layer.
- **Remediation:** Phase 3 — Add `envoy.filters.http.ratelimit` or `ext_authz` filter to listener template.
- **Remediation Phase:** 3

---

## Domain 4: Observability

### FINDING OBS-001: Metrics Endpoints Return JSON (CRITICAL)
- **Files:** [broker/main.py](file:///c:/Users/hashm/Desktop/Projects/RUVAMCO/broker/main.py#L197-L204), [control_plane/main.py](file:///c:/Users/hashm/Desktop/Projects/RUVAMCO/control_plane/main.py#L149-L157)
- **Root Cause:** FastAPI endpoints return Python dicts, auto-serialized to `application/json`. Prometheus expects `text/plain; version=0.0.4` exposition format.
- **Impact:** Prometheus scraper rejects all metrics. Monitoring is completely blind for broker and control plane.
- **Remediation:** Phase 1 — Use `prometheus_client.generate_latest()`.
- **Remediation Phase:** 1

### FINDING OBS-002: No Liveness/Readiness Probe Split (HIGH)
- **Files:** All services — `/health` endpoint only
- **Root Cause:** Single `/health` endpoint conflates liveness and readiness. In Kubernetes, liveness failures trigger restarts; readiness failures stop traffic routing.
- **Impact:** Pods warming up (connecting to DynamoDB/S3) receive traffic prematurely. Pods with transient dependency failures get restarted instead of being drained.
- **Remediation:** Phase 1 — Add `/health/live` and `/health/ready`.
- **Remediation Phase:** 1

### FINDING OBS-003: Hardcoded instance_id="local" in Observability Sidecar (MEDIUM)
- **Files:** [observability/main.py](file:///c:/Users/hashm/Desktop/Projects/RUVAMCO/sidecars/observability/main.py#L127)
- **Root Cause:** `ACTIVE_CONNECTIONS.labels(instance_id="local")` hardcodes the label value.
- **Impact:** All instances report identical label, making per-instance dashboarding and alerting impossible.
- **Remediation:** Phase 1 — Read instance_id from environment or Envoy admin node metadata.
- **Remediation Phase:** 1

### FINDING OBS-004: No Structured Logging (MEDIUM)
- **Files:** All Python services
- **Root Cause:** `logging.basicConfig(level=logging.INFO)` with format strings. No JSON formatting, no request IDs, no correlation IDs.
- **Impact:** Multi-service debugging requires manual timestamp correlation across unstructured log streams.
- **Remediation:** Phase 6 — Structured JSON logging with trace_id injection.
- **Remediation Phase:** 6

### FINDING OBS-005: OpenTelemetry Not Initialized (LOW)
- **Files:** [docker-compose.yml](file:///c:/Users/hashm/Desktop/Projects/RUVAMCO/docker-compose.yml#L129-L135), [.env.example](file:///c:/Users/hashm/Desktop/Projects/RUVAMCO/.env.example#L44)
- **Root Cause:** Jaeger container deployed, `OTEL_EXPORTER_OTLP_ENDPOINT` defined, but no service initializes an OpenTelemetry SDK.
- **Impact:** Jaeger receives no trace data. Distributed tracing is cosmetic only.
- **Remediation:** Phase 6 — Initialize OTLP tracer providers in all services.
- **Remediation Phase:** 6

---

## Domain 5: Infrastructure & IAM

### FINDING INF-001: Wildcard IAM Actions (CRITICAL)
- **Files:** [control-plane/main.tf](file:///c:/Users/hashm/Desktop/Projects/RUVAMCO/terraform/modules/control-plane/main.tf#L61-L89)
- **Root Cause:** Task role policy uses `dynamodb:*`, `sqs:*`, `s3:*`, `route53:*`, `cloudfront:*`, `elasticloadbalancing:*`. The Route53/CloudFront/ELB statement uses `Resource: "*"`.
- **Impact:** Compromised ECS task can delete any DynamoDB table, S3 bucket, Route53 zone, or CloudFront distribution in the account. Privilege escalation via `s3:PutBucketPolicy` or `iam:PassRole` (if inherited).
- **Remediation:** Phase 4 — Minimum-privilege action scoping with exact ARNs.
- **Remediation Phase:** 4

### FINDING INF-002: Placeholder Hosted Zone ID (HIGH)
- **Files:** [dns.py](file:///c:/Users/hashm/Desktop/Projects/RUVAMCO/worker/provisioners/dns.py#L20)
- **Root Cause:** `DEFAULT_HOSTED_ZONE_ID = "Z0000000000000"` — a fake zone ID.
- **Impact:** All Route53 API calls fail with `NoSuchHostedZone`. DNS provisioning is non-functional, but instances may still be marked active (error is caught and re-raised, but the worker's `process_message` catches the exception at a higher level).
- **Remediation:** Phase 1 — Read from environment variable.
- **Remediation Phase:** 1

### FINDING INF-003: CloudFront Invalid Certificate Configuration (HIGH)
- **Files:** [cdn.py](file:///c:/Users/hashm/Desktop/Projects/RUVAMCO/worker/provisioners/cdn.py#L77-L82)
- **Root Cause:** `CloudFrontDefaultCertificate: True` paired with `Aliases: {"Items": [domain]}` is rejected by AWS API — custom aliases require a custom SSL certificate.
- **Impact:** Enterprise plan CDN provisioning fails at runtime with `InvalidViewerCertificate`.
- **Remediation:** Phase 3 — Require ACM certificate ARN for custom domain aliases.
- **Remediation Phase:** 3

### FINDING INF-004: No SQS Encryption or Queue Policy (MEDIUM)
- **Files:** [main.tf](file:///c:/Users/hashm/Desktop/Projects/RUVAMCO/terraform/main.tf#L105-L128)
- **Root Cause:** SQS queue has no `kms_master_key_id` and no resource policy.
- **Impact:** Messages (containing provisioning parameters, domain names, backend addresses) stored unencrypted. Any IAM entity with `sqs:SendMessage` can inject tasks.
- **Remediation:** Phase 4 — Add KMS encryption and resource policy.
- **Remediation Phase:** 4

### FINDING INF-005: S3 Uses AES256 Instead of KMS (LOW)
- **Files:** [main.tf](file:///c:/Users/hashm/Desktop/Projects/RUVAMCO/terraform/main.tf#L145-L152)
- **Root Cause:** SSE configured with `sse_algorithm = "AES256"` (S3-managed keys).
- **Impact:** No key rotation audit trail, no CloudTrail key-level events. Insufficient for SOC 2/HIPAA.
- **Remediation:** Phase 4 — Migrate to KMS CMK.
- **Remediation Phase:** 4

### FINDING INF-006: Terraform State Backend Hardcoded (MEDIUM)
- **Files:** [main.tf](file:///c:/Users/hashm/Desktop/Projects/RUVAMCO/terraform/main.tf#L22-L28)
- **Root Cause:** S3 backend bucket name, key, and region are literal strings.
- **Impact:** Multi-environment (dev/staging/prod) or multi-region deployments will collide on state.
- **Remediation:** Phase 4 — Use `-backend-config` partial configuration or Terragrunt.
- **Remediation Phase:** 4

### FINDING INF-007: Empty proxy_ami_id Default (MEDIUM)
- **Files:** [variables.tf](file:///c:/Users/hashm/Desktop/Projects/RUVAMCO/terraform/variables.tf#L70-L74)
- **Root Cause:** `default = ""` — `terraform apply` without providing `proxy_ami_id` will use empty string, causing ASG launch failure.
- **Impact:** Deployment failure on first apply without explicit tfvars.
- **Remediation:** Phase 4 — Add validation constraint.
- **Remediation Phase:** 4

---

## Domain 6: CI/CD

### FINDING CICD-001: Sidecars Not in CI (CRITICAL)
- **Files:** [ci.yml](file:///c:/Users/hashm/Desktop/Projects/RUVAMCO/.github/workflows/ci.yml#L20)
- **Root Cause:** Build matrix is `[broker, worker, control_plane, cli]`. Rust auth sidecar and Go ratelimit sidecar are absent.
- **Impact:** Broken compilations, failing tests, and security vulnerabilities in sidecars are invisible until deployment.
- **Remediation:** Phase 5 — Add Rust and Go build/test/lint jobs.
- **Remediation Phase:** 5

### FINDING CICD-002: Auto-Approve Terraform Apply (CRITICAL)
- **Files:** [ci.yml](file:///c:/Users/hashm/Desktop/Projects/RUVAMCO/.github/workflows/ci.yml#L132-L133)
- **Root Cause:** `terraform apply -auto-approve` runs on every push to main without human approval.
- **Impact:** Any infrastructure change merged to main is immediately applied to production. Violates change management, GitOps, and SOC 2 controls.
- **Remediation:** Phase 5 — Remove auto-approve; add environment protection rules.
- **Remediation Phase:** 5

### FINDING CICD-003: Long-Term AWS Credentials (HIGH)
- **Files:** [ci.yml](file:///c:/Users/hashm/Desktop/Projects/RUVAMCO/.github/workflows/ci.yml#L117-L118)
- **Root Cause:** `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` stored as GitHub secrets — long-lived IAM user credentials.
- **Impact:** Persistent credential exposure risk. If repo is compromised, keys remain valid until manually rotated.
- **Remediation:** Phase 5 — Migrate to OIDC federation.
- **Remediation Phase:** 5

### FINDING CICD-004: No Image Scanning (HIGH)
- **Files:** [ci.yml](file:///c:/Users/hashm/Desktop/Projects/RUVAMCO/.github/workflows/ci.yml#L61-L104)
- **Root Cause:** No `trivy`, `grype`, or `docker scout` step in CI.
- **Impact:** CVEs in base images (Python, Rust, Go, Envoy) are never detected.
- **Remediation:** Phase 5 — Add trivy scan after each build-push.
- **Remediation Phase:** 5

### FINDING CICD-005: No IaC Security Scanning (HIGH)
- **Files:** CI pipeline
- **Root Cause:** No `tfsec`, `checkov`, or `terrascan` step.
- **Impact:** Wildcard IAM policies (INF-001) would be caught immediately by any scanner.
- **Remediation:** Phase 5 — Add tfsec/checkov job.
- **Remediation Phase:** 5

### FINDING CICD-006: :latest Tag in Production (MEDIUM)
- **Files:** [ci.yml](file:///c:/Users/hashm/Desktop/Projects/RUVAMCO/.github/workflows/ci.yml#L83)
- **Root Cause:** `tags: ruvamco/broker:latest,ruvamco/broker:${{ github.sha }}` — `:latest` is mutable.
- **Impact:** Kubernetes nodes pull inconsistent images based on cache state.
- **Remediation:** Phase 5 — Remove `:latest` from production publishing.
- **Remediation Phase:** 5

---

## Domain 7: Worker Subsystem

### FINDING WRK-001: Hardcoded SQS URL with Placeholder Account (HIGH)
- **Files:** [worker/main.py](file:///c:/Users/hashm/Desktop/Projects/RUVAMCO/worker/main.py#L33)
- **Root Cause:** `"https://sqs.us-east-1.amazonaws.com/account/ruvamco-tasks"` — `account` is not a valid AWS account ID.
- **Impact:** SQS API call fails with `NonExistentQueue` in both production and local environments.
- **Remediation:** Phase 1 — Read from `SQS_QUEUE_URL` environment variable.
- **Remediation Phase:** 1

### FINDING WRK-002: DynamoDB Client Created Per-Call Without Endpoint (HIGH)
- **Files:** [worker/main.py](file:///c:/Users/hashm/Desktop/Projects/RUVAMCO/worker/main.py#L173-L174)
- **Root Cause:** `mark_active()`, `mark_failed()`, `mark_deleted()` each create `boto3.resource('dynamodb')` without passing `endpoint_url`. The `Table('ruvamco-instances')` name is hardcoded.
- **Impact:** (1) Ignores `DYNAMODB_ENDPOINT` so local dev fails. (2) Creates new boto3 sessions on every status update — connection pool overhead. (3) Table name hardcoded instead of configurable.
- **Remediation:** Phase 1 — Create shared DynamoDB resource in `__init__` with endpoint injection.
- **Remediation Phase:** 1

### FINDING WRK-003: SQS Client Created Without Endpoint (HIGH)
- **Files:** [worker/main.py](file:///c:/Users/hashm/Desktop/Projects/RUVAMCO/worker/main.py#L27)
- **Root Cause:** `self.sqs = boto3.client('sqs')` — no `endpoint_url` parameter.
- **Impact:** Worker cannot communicate with ElasticMQ in local development.
- **Remediation:** Phase 1 — Pass `SQS_ENDPOINT` to boto3 client constructor.
- **Remediation Phase:** 1

### FINDING WRK-004: Broker Settings Ignore Endpoint Variables (HIGH)
- **Files:** [broker/main.py](file:///c:/Users/hashm/Desktop/Projects/RUVAMCO/broker/main.py#L28-L38)
- **Root Cause:** `Settings` class has no `dynamodb_endpoint` or `sqs_endpoint` fields. `DatabaseManager` and `QueueManager` are constructed without `endpoint_url`.
- **Impact:** Broker cannot use DynamoDB-local or ElasticMQ. Docker-compose environment variables are ignored.
- **Remediation:** Phase 1 — Add endpoint fields to Settings; pass to constructors.
- **Remediation Phase:** 1

---

## Summary Statistics

| Severity | Count |
|---|---|
| CRITICAL | 7 |
| HIGH | 15 |
| MEDIUM | 8 |
| LOW | 3 |
| **Total** | **33** |

| Remediation Phase | Finding Count |
|---|---|
| Phase 1 | 8 |
| Phase 2 | 5 |
| Phase 3 | 10 |
| Phase 4 | 5 |
| Phase 5 | 6 |
| Phase 6 | 2 |

---

*Meer Corporation — Confidential — Architecture Findings Report*
