# RUVAMCO — Remediation Task List
**Meer Corporation — Execution Checklist**
**Version: 2.0 — Dependency-Ordered**

> [!IMPORTANT]
> Tasks are ordered by dependency. Within each phase, P0 items must complete before P1 items. Phases must execute sequentially — Phase N+1 depends on Phase N completion.

---

## Phase 1 — Runtime & Configuration Stabilization

### Environment & Endpoint Injection
- [ ] **P0** — Refactor `broker/main.py` `Settings` class to read `DYNAMODB_ENDPOINT`, `SQS_ENDPOINT`, `SQS_QUEUE_URL` from environment variables with `os.environ.get()`
- [ ] **P0** — Pass `endpoint_url` from Settings to `DatabaseManager()` and `QueueManager()` constructors in `broker/main.py`
- [ ] **P0** — Refactor `worker/main.py` `ProvisioningWorker.__init__()` to read `SQS_QUEUE_URL`, `CONTROL_PLANE_URL`, `DYNAMODB_ENDPOINT`, `DYNAMODB_TABLE` from environment
- [ ] **P0** — Fix `worker/main.py` `mark_active()`, `mark_failed()`, `mark_deleted()` to use shared DynamoDB resource with endpoint injection instead of creating new `boto3.resource('dynamodb')` each call
- [ ] **P0** — Fix `worker/provisioners/dns.py` to read `DNS_HOSTED_ZONE_ID` from environment instead of hardcoded `"Z0000000000000"`

### Metrics Endpoints
- [ ] **P0** — Replace `broker/main.py` `/metrics` endpoint: remove JSON dict, add `prometheus_client` library, return `Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)`
- [ ] **P0** — Add Prometheus counters/histograms to broker: `ruvamco_broker_provisioning_requests_total{plan,status}`, `ruvamco_broker_provisioning_duration_seconds{plan}`, `ruvamco_broker_active_instances` gauge
- [ ] **P0** — Replace `control_plane/main.py` `/metrics` endpoint: remove JSON dict, use `prometheus_client generate_latest`
- [ ] **P0** — Add Prometheus metrics to control plane: `ruvamco_cp_cache_size`, `ruvamco_cp_config_generations_total`, `ruvamco_cp_active_instances`
- [ ] **P0** — Add `prometheus_client` to `broker/requirements.txt` and `control_plane/requirements.txt`

### Health Endpoints
- [ ] **P1** — Add `/health/live` (returns 200 if process alive) to broker, worker (HTTP wrapper), control plane
- [ ] **P1** — Add `/health/ready` (returns 200 only if DynamoDB/SQS/S3 connections verified) to broker, worker, control plane

### Lifecycle & Import Fixes
- [ ] **P1** — Migrate `control_plane/main.py` from `@app.on_event("startup")` to `@asynccontextmanager lifespan` pattern (matching broker)
- [ ] **P0** — Fix `control_plane/main.py` line 60: wrap `from .generated import` in try/except to handle missing protobuf stubs gracefully during development

### Verification — Phase 1
- [ ] `docker-compose up` completes with all services healthy
- [ ] `curl localhost:8080/metrics` returns plaintext Prometheus format
- [ ] `curl localhost:8081/metrics` (control plane HTTP) returns plaintext Prometheus format
- [ ] Worker picks up SQS message from ElasticMQ and writes to local DynamoDB
- [ ] Prometheus shows all scrape targets as UP

---

## Phase 2 — Control Plane Protocol Correctness

### Protobuf Generation
- [ ] **P0** — Create `scripts/gen_proto.sh` to download Envoy xDS proto definitions and generate Python gRPC stubs
- [ ] **P0** — Generate `control_plane/generated/` directory with `envoy_service_discovery_pb2.py` and `envoy_service_discovery_pb2_grpc.py`

### ADS Implementation
- [ ] **P0** — Implement `StreamAggregatedResources()` as an async generator on `AggregatedDiscoveryService` class
- [ ] **P0** — Parse incoming `DiscoveryRequest`: extract `node.id`, `type_url`, `version_info`, `response_nonce`
- [ ] **P0** — Implement nonce generation: assign `uuid.uuid4().hex` to each outgoing `DiscoveryResponse`
- [ ] **P0** — Implement ACK detection: `version_info == last_sent_version AND nonce == last_sent_nonce`
- [ ] **P0** — Implement NACK detection: `version_info != last_sent_version AND nonce == last_sent_nonce`, log `error_detail`
- [ ] **P0** — Implement per-node subscription state: `Dict[node_id, NodeState]` tracking last ACKed version per resource type
- [ ] **P0** — Implement snapshot versioning: use monotonically increasing counter combined with content hash

### Resource Ordering
- [ ] **P1** — Implement resource type ordering in snapshot delivery: CDS → EDS → LDS → RDS (Envoy dependency order)
- [ ] **P1** — Implement push-on-change: when `/v1/reload` is called, notify all connected streams for that instance

### xDS Metrics
- [ ] **P1** — Add `ruvamco_cp_xds_snapshots_total{instance_id}` counter
- [ ] **P1** — Add `ruvamco_cp_xds_nacks_total{instance_id}` counter
- [ ] **P1** — Add `ruvamco_cp_xds_connected_nodes` gauge

### Envoy Bootstrap
- [ ] **P0** — Create `envoy-bootstrap.yaml` with static ADS cluster pointing to `control-plane:18000`
- [ ] **P0** — Update `docker-compose.yml` Envoy service to mount bootstrap config

### Verification — Phase 2
- [ ] Envoy connects to control plane gRPC and logs successful ADS stream establishment
- [ ] `curl localhost:9901/config_dump` shows dynamically received listeners/clusters/routes
- [ ] Updating S3 context + calling `/v1/reload` → Envoy receives new config within 5s
- [ ] Control plane logs show ACK receipt with matching nonce
- [ ] Malformed template → control plane logs NACK with error_detail

---

## Phase 3 — Security Architecture Enforcement

### JWT RS256 Migration
- [ ] **P0** — Generate RSA-4096 keypair: `openssl genrsa -out ruvamco-private.pem 4096 && openssl rsa -in ruvamco-private.pem -pubout -out ruvamco-public.pem`
- [ ] **P0** — Create `broker/jwks.py`: endpoint that serves public key as JWKS JSON at `/.well-known/jwks.json`
- [ ] **P0** — Modify `broker/auth.py`: replace `JWT_SECRET` with `JWT_PRIVATE_KEY_PATH` for signing; replace `JWT_ALGORITHM` default from `HS256` to `RS256`
- [ ] **P0** — Modify `broker/auth.py` `decode_jwt_token()`: fetch public key from JWKS URL instead of using symmetric secret
- [ ] **P0** — Remove `JWT_SECRET` and `JWT_ALGORITHM=HS256` from `.env.example`; add `JWT_PRIVATE_KEY_PATH`, `JWKS_URL`
- [ ] **P0** — Add KID (Key ID) to JWT header during signing; support KID-based key selection in validation

### Auth Sidecar Completion
- [ ] **P0** — Implement `refresh_jwks()` in `sidecars/auth/src/main.rs`: HTTP GET to JWKS URL, parse JWK set, extract `kid`/`n`/`e`, build `DecodingKey::from_rsa_components()`, store in `jwks_cache` keyed by `kid`
- [ ] **P0** — Implement KID-based key selection in `validate_token()`: parse JWT header for `kid`, look up specific key instead of iterating all keys
- [ ] **P0** — Implement enforcing `auth_middleware()`: extract Bearer token, call `validate_token`, return 401 on failure, pass `X-Auth-Subject` header downstream on success
- [ ] **P1** — Add auth sidecar Prometheus metrics: `ruvamco_auth_requests_total{result}`, `ruvamco_auth_jwks_refresh_total{status}`, `ruvamco_auth_jwks_cache_size`

### Rate Limiter Redis Integration
- [ ] **P0** — Instantiate `go-redis/redis/v8` client in `main.go` using `REDIS_ADDR` config
- [ ] **P0** — Implement Lua sliding-window rate limit script: `KEYS[1]=ratelimit:{key}`, atomically check + increment within window
- [ ] **P0** — Replace `golang.org/x/time/rate` primary path with Redis EVALSHA call
- [ ] **P0** — Implement degraded mode: track consecutive Redis failures; after N failures, fall back to in-process limiter with 50% threshold reduction
- [ ] **P0** — Add `ratelimit_redis_failures_total` Prometheus counter
- [ ] **P0** — Add `ratelimit_degraded_mode` gauge (0/1)
- [ ] **P1** — Add `RATELIMIT_FAIL_CLOSED` env var for fail-closed mode (reject all on Redis failure)

### Envoy Filter Chain Updates
- [ ] **P0** — Add `ext_authz` HTTP filter to `listener.j2` pointing to auth sidecar on port 8081
- [ ] **P0** — Add `envoy.filters.http.ratelimit` filter to `listener.j2` pointing to rate limit sidecar on port 8082
- [ ] **P1** — Add upstream TLS context block to `cluster.j2` for backend connections

### mTLS Foundation
- [ ] **P1** — Create `scripts/gen-dev-certs.sh`: generate root CA, intermediate CA, leaf certs for each service
- [ ] **P0** — Configure `control_plane/main.py` gRPC server with TLS credentials (server cert + key)
- [ ] **P1** — Configure Envoy bootstrap with client cert for xDS cluster connection
- [ ] **P1** — Document production SPIFFE/SPIRE or cert-manager strategy (planning only for Phase 6)

### CloudFront Fix
- [ ] **P0** — Fix `worker/provisioners/cdn.py`: remove `CloudFrontDefaultCertificate: True` when `Aliases` is set; require `acm_certificate_arn` parameter or provision ACM cert

### Verification — Phase 3
- [ ] HS256 tokens are rejected by both broker and auth sidecar
- [ ] RS256 tokens with valid kid are accepted
- [ ] Rate limiter under burst: Redis MONITOR shows sliding window operations
- [ ] Kill Redis → sidecar logs degraded mode entry; `ratelimit_degraded_mode` == 1
- [ ] Restart Redis → sidecar recovers; `ratelimit_degraded_mode` == 0
- [ ] `nmap --script ssl-enum-ciphers localhost:18000` shows TLS

---

## Phase 4 — Infrastructure Hardening

### IAM Restriction
- [ ] **P0** — Replace `dynamodb:*` with: `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:DeleteItem`, `dynamodb:Scan`, `dynamodb:Query`, `dynamodb:DescribeTable`
- [ ] **P0** — Replace `sqs:*` with: `sqs:SendMessage`, `sqs:ReceiveMessage`, `sqs:DeleteMessage`, `sqs:GetQueueAttributes`, `sqs:GetQueueUrl`
- [ ] **P0** — Replace `s3:*` with: `s3:GetObject`, `s3:PutObject`, `s3:ListBucket`, `s3:DeleteObject`
- [ ] **P0** — Restrict Route53 actions to: `route53:ChangeResourceRecordSets`, `route53:ListResourceRecordSets` with `Resource: "arn:aws:route53:::hostedzone/${var.hosted_zone_id}"`
- [ ] **P0** — Restrict CloudFront actions to: `cloudfront:CreateDistribution`, `cloudfront:GetDistribution`, `cloudfront:UpdateDistribution`, `cloudfront:DeleteDistribution` with tag-based conditions
- [ ] **P0** — Restrict ELB actions to specific ALB ARNs
- [ ] **P0** — Add `data "aws_caller_identity" "current" {}` and interpolate account ID into all resource ARNs

### Encryption & Access Controls
- [ ] **P1** — Add `kms_master_key_id` to SQS queue resource
- [ ] **P1** — Add SQS resource policy restricting `SendMessage` to ECS task role only
- [ ] **P1** — Migrate S3 SSE from `AES256` to `aws:kms` with customer-managed key
- [ ] **P0** — Add `aws_s3_bucket_public_access_block` to context bucket (block all public access)

### Terraform Hardening
- [ ] **P1** — Add validation to `proxy_ami_id` variable: `condition = length(var.proxy_ami_id) > 0`
- [ ] **P1** — Enable DynamoDB deletion protection: `deletion_protection_enabled = true`
- [ ] **P1** — Parameterize Terraform backend configuration for multi-environment support

### Verification — Phase 4
- [ ] `aws iam simulate-principal-policy` confirms task role cannot `dynamodb:DeleteTable`
- [ ] `tfsec ./terraform` returns 0 HIGH/CRITICAL findings
- [ ] `checkov -d ./terraform` passes
- [ ] S3 bucket public access block verified via `aws s3api get-public-access-block`

---

## Phase 5 — CI/CD & Delivery Hardening

### Sidecar Build Matrix
- [ ] **P0** — Add CI job: `build-auth-sidecar` — `rustup`, `cargo build --release`, `cargo test`, `cargo clippy`
- [ ] **P0** — Add CI job: `build-ratelimit-sidecar` — `go build ./...`, `go test ./...`, `go vet ./...`
- [ ] **P0** — Add `cargo audit` step to auth sidecar job
- [ ] **P0** — Add `govulncheck ./...` step to ratelimit sidecar job

### Security Scanning
- [ ] **P0** — Add `tfsec` or `checkov` job scanning `terraform/` directory
- [ ] **P0** — Add `trivy image` scan after each Docker build-push step
- [ ] **P0** — Add `bandit` scan for observability sidecar (Python)

### Deployment Gates
- [ ] **P0** — Remove `terraform apply -auto-approve` from CI
- [ ] **P0** — Add GitHub environment `production` with required reviewers
- [ ] **P0** — Gate `terraform apply` behind `environment: production` approval
- [ ] **P0** — Migrate AWS CI auth from long-term keys to OIDC: `aws-actions/configure-aws-credentials@v4` with `role-to-assume`

### Image Publishing
- [ ] **P0** — Add Docker build+push for auth sidecar (multi-stage Rust build)
- [ ] **P0** — Add Docker build+push for ratelimit sidecar (multi-stage Go build)
- [ ] **P0** — Add Docker build+push for observability sidecar
- [ ] **P1** — Remove `:latest` tag from production image publishing; use `${{ github.sha }}` and semver only

### Verification — Phase 5
- [ ] PR to main triggers: Python tests + Rust build + Go build + Terraform scan + image scans
- [ ] `cargo audit` returns 0 known vulnerabilities
- [ ] `govulncheck` returns clean
- [ ] `trivy image ruvamco/broker:sha` returns 0 CRITICAL CVEs
- [ ] Merge to main does NOT auto-apply Terraform
- [ ] AWS credentials obtained via OIDC (no `AWS_ACCESS_KEY_ID` secret used)

---

## Phase 6 — Future Production Hardening (Roadmap)

### OpenTelemetry
- [ ] Initialize OTLP tracer provider in broker, worker, control plane
- [ ] Instrument FastAPI with `opentelemetry-instrumentation-fastapi`
- [ ] Instrument gRPC with `opentelemetry-instrumentation-grpc`
- [ ] Deploy OpenTelemetry Collector as sidecar or DaemonSet
- [ ] Ship traces to Jaeger/Tempo

### SPIFFE/SPIRE
- [ ] Deploy SPIRE Server (Kubernetes StatefulSet or standalone)
- [ ] Deploy SPIRE Agent (DaemonSet)
- [ ] Configure Envoy SDS to fetch certs from SPIRE Agent socket
- [ ] Migrate all mTLS from self-signed to SPIRE-issued SVIDs

### Adaptive Rate Limiting
- [ ] Implement traffic pattern analysis
- [ ] Implement dynamic threshold adjustment
- [ ] Add ML-based anomaly detection for DDoS mitigation

### Delta xDS
- [ ] Evaluate fleet size threshold where Delta xDS becomes necessary (>1000 nodes)
- [ ] Prototype `DeltaAggregatedResources` handler
- [ ] Benchmark SotW vs Delta for large resource sets

### Advanced Rollout Controls
- [ ] Implement weighted cluster routing via xDS for canary deployments
- [ ] Implement automatic rollback on NACK rate exceeding threshold
- [ ] Implement progressive rollout controller

---

*Last updated: 2026-05-23 — PLAN ONLY — No items executed*
