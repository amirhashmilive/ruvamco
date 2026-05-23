# RUVAMCO — Risk Register
**Meer Corporation — Risk Management Office**
**Version: 1.0 — INITIAL CATALOG**

This risk register catalogs the security, reliability, performance, and operational risks identified during the architectural and source code audit of the RUVAMCO platform.

---

## 1. Risk Matrix Reference

Risks are evaluated using a combination of **Likelihood** (Unlikely, Possible, Likely) and **Impact** (Minor, Moderate, Major) to determine the overall **Risk Rating** (Low, Medium, High, Critical).

| Likelihood \ Impact | Minor | Moderate | Major |
|---|---|---|---|
| **Likely** | Medium | High | **Critical** |
| **Possible** | Low | Medium | High |
| **Unlikely** | Low | Low | Medium |

---

## 2. Identified Risks Catalog

### R-01 — Symmetric JWT (HS256) Token Forgery (CRITICAL)
- **Domain**: Security
- **Likelihood**: Possible | **Impact**: Major | **Severity**: **Critical**
- **Affected Components**: `broker/auth.py`, `sidecars/auth`
- **Description**: The broker uses `HS256` symmetric signing with a hardcoded fallback secret `"change-me-in-production"`.
- **Business Impact**: An attacker who discovers the default credentials or extracts the secret from container logs can forge valid tokens with any payload or role, bypassing downstream API authentication entirely.
- **Remediation Phase**: Phase 3
- **Remediation Action**: Migrate token signing and validation to `RS256` asymmetric keys. Expose public keys via a JWKS endpoint (`/.well-known/jwks.json`) and configure the Envoy/auth sidecar to fetch and parse the keys.

---

### R-02 — Insecure xDS Control Plane Communication (HIGH)
- **Domain**: Security
- **Likelihood**: Possible | **Impact**: Major | **Severity**: **High**
- **Affected Components**: `control_plane/main.py`, `envoy-bootstrap`
- **Description**: The xDS control plane listens on an insecure gRPC port without TLS.
- **Business Impact**: Intermediary attackers inside the VPC or network segment can listen to configuration streams, capture routing tables and target addresses, or inject fake discovery responses to redirect client traffic to malicious hosts.
- **Remediation Phase**: Phase 3 (gRPC TLS Setup) & Phase 6 (SPIFFE/SPIRE)
- **Remediation Action**: Configure the FastAPI/gRPC server in the control plane with TLS credentials. Update Envoy bootstrap configuration to verify the control plane's certificate.

---

### R-03 — Wildcard AWS IAM Permissions (HIGH)
- **Domain**: Security
- **Likelihood**: Unlikely | **Impact**: Major | **Severity**: **Medium**
- **Affected Components**: `terraform/modules/control-plane/main.tf`
- **Description**: The ECS task role is granted wildcard access to DynamoDB tables (`dynamodb:*`), SQS queues (`sqs:*`), Route 53 resources (`route53:*`), and CloudFront distributions (`cloudfront:*`).
- **Business Impact**: If any RUVAMCO service container is compromised, the attacker can leverage the task role credentials to delete state databases, wipe queues, inject arbitrary record sets across Route 53 zones, or alter unrelated CDN setups in the same AWS account.
- **Remediation Phase**: Phase 4
- **Remediation Action**: Replace broad action categories (e.g., `dynamodb:*`) with specific APIs (e.g., `dynamodb:GetItem`, `dynamodb:PutItem`). Scope resources using exact ARNs containing AWS region and account ID instead of `*`.

---

### R-04 — Distributed Rate Limiting Bypass (HIGH)
- **Domain**: Reliability / Reliability
- **Likelihood**: Likely | **Impact**: Moderate | **Severity**: **High**
- **Affected Components**: `sidecars/ratelimit` (Go)
- **Description**: The rate limiting sidecar relies on local memory counters (`golang.org/x/time/rate`) and is not connected to the Redis cluster, despite referencing configuration options.
- **Business Impact**: Rate limit state is completely isolated to individual Envoy container pods. An attacker can bypass the configured requests-per-second (RPS) limits by distributing requests across multiple pods, potentially saturating downstream target services.
- **Remediation Phase**: Phase 3
- **Remediation Action**: Implement Redis client connection logic and instantiate a sliding-window rate limit using atomic Lua scripts on the Redis cluster. Provide local degraded backup.

---

### R-05 — Authentication Sidecar Cache Exhaustion / Crash (HIGH)
- **Domain**: Reliability
- **Likelihood**: Likely | **Impact**: Moderate | **Severity**: **High**
- **Affected Components**: `sidecars/auth` (Rust)
- **Description**: The Rust-based auth sidecar contains a stubbed `refresh_jwks()` function which fails to fetch or cache public keys, resulting in all token verification attempts failing.
- **Business Impact**: Deploying the sidecar in its current state causes 100% request failure on protected routes, creating a complete denial of service.
- **Remediation Phase**: Phase 3
- **Remediation Action**: Write the async HTTP GET handler to fetch the JWKS payload, compile RSA public decoding keys, cache keys by KID, and select the appropriate key during signature checks.

---

### R-06 — AWS CloudFront Deployment Failure (HIGH)
- **Domain**: Reliability
- **Likelihood**: Likely | **Impact**: Moderate | **Severity**: **High**
- **Affected Components**: `worker/provisioners/cdn.py`
- **Description**: The CloudFront CDN provisioner attempts to configure custom domain names (`Aliases`) while utilizing the default CloudFront SSL certificate, which is rejected by AWS APIs.
- **Business Impact**: Provisioning requests for the Enterprise plan (which includes CloudFront) fail silently at runtime during the worker's AWS api call, preventing client setups.
- **Remediation Phase**: Phase 3
- **Remediation Action**: Add parameterization for custom ACM certificates or provision certificate sets dynamically within the AWS Route 53 / ACM verification loop prior to CDN instantiation.

---

### R-07 — Monitoring Metrics Ingestion Black Hole (HIGH)
- **Domain**: Observability
- **Likelihood**: Likely | **Impact**: Moderate | **Severity**: **High**
- **Affected Components**: `broker/main.py`, `control_plane/main.py`
- **Description**: The `/metrics` endpoints serialize Prometheus metrics as JSON objects instead of plaintext standard exposition format.
- **Business Impact**: Prometheus scrapers raise parsing exceptions and refuse to ingest any service statistics, blinding operators to request rates, errors, queue levels, and worker health.
- **Remediation Phase**: Phase 1
- **Remediation Action**: Pull in `prometheus_client` packages, bind counters/gauges/histograms, and configure the HTTP route handlers to return plaintext format.

---

### R-08 — DynamoDB table scans causing latency cascades (MEDIUM)
- **Domain**: Performance
- **Likelihood**: Possible | **Impact**: Moderate | **Severity**: **Medium**
- **Affected Components**: `broker/database.py`, `control_plane/context_manager.py`
- **Description**: `get_all_instances()` scans the entire database table and applies filters on the server, causing linear performance degradation as the fleet scales.
- **Business Impact**: Scrapes of `/metrics` (which calls database queries on every cycle) and routine control plane refreshes experience exponential latency spikes, leading to timeout failures, CPU exhaustion, and AWS read cost spikes.
- **Remediation Phase**: Phase 1
- **Remediation Action**: Replace table scans with scoped Global Secondary Index (GSI) queries to lookup instances by status or target properties.

---

### R-09 — Uncontrolled Terraform Production Application (MEDIUM)
- **Domain**: Operational / CI/CD
- **Likelihood**: Possible | **Impact**: Moderate | **Severity**: **Medium**
- **Affected Components**: `.github/workflows/ci.yml`
- **Description**: The CI workflow executes `terraform apply -auto-approve` immediately on code merge to the `main` branch.
- **Business Impact**: Misconfigurations, state mistakes, or security policy errors applied to Terraform code are immediately forced into live production networks without manual reviews, creating high risk for configuration-driven outages.
- **Remediation Phase**: Phase 5
- **Remediation Action**: Isolate the plan step in pull request workflows. Gate the apply step behind manual approval constraints using GitHub Environment approvals.

---

### R-10 — Persistent AWS Credential Leakage in CI (MEDIUM)
- **Domain**: Operational / Security
- **Likelihood**: Possible | **Impact**: Moderate | **Severity**: **Medium**
- **Affected Components**: `.github/workflows/ci.yml`
- **Description**: Long-term AWS IAM user access keys are configured directly in GitHub secrets.
- **Business Impact**: If the GitHub repository or action runner environment is compromised, the static keys can be extracted and used externally to access AWS resources indefinitely, until keys are rotated manually.
- **Remediation Phase**: Phase 5
- **Remediation Action**: Establish an OpenID Connect (OIDC) trust relationship between AWS and GitHub. Obtain short-lived access credentials dynamically using OIDC roles during runs.

---

### R-11 — Compilation Errors Leaking into Deployments (MEDIUM)
- **Domain**: Operational / CI/CD
- **Likelihood**: Possible | **Impact**: Moderate | **Severity**: **Medium**
- **Affected Components**: `.github/workflows/ci.yml`
- **Description**: The Rust (auth) and Go (rate limit) sidecars are missing from the CI build matrix.
- **Business Impact**: Compilation issues, code syntax failures, or dependency conflicts are undetected in PR checks, resulting in broken builds deployed directly to container registries.
- **Remediation Phase**: Phase 5
- **Remediation Action**: Expand the CI build runner matrix to include Go and Rust compilers, executing tests and linters for all components prior to container build phases.

---
*Last updated: 2026-05-23 | Prepared by Meer Corporation Risk Management*
