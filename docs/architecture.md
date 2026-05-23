# RUVAMCO Architecture

## System Overview

RUVAMCO follows a **control plane / data plane** separation pattern inspired by Kubernetes and Istio. The control plane manages configuration state and pushes dynamic updates; the data plane (Envoy proxy fleet) handles actual traffic.

```
┌─────────────────────────────────────────────────────────────┐
│                    DEVELOPER WORKFLOW                       │
│                                                             │
│  YAML Config ──▶ CLI / Git Push ──▶ Broker API (< 30s)     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      CONTROL PLANE                          │
│                                                             │
│  Broker (FastAPI)  ──▶  SQS Queue  ──▶  Worker (Async)     │
│       │                                     │               │
│       ▼                                     ▼               │
│  DynamoDB (State)              S3 (Contexts) + Route 53     │
│                                     │                       │
│                                     ▼                       │
│                          Control Plane (xDS Server)         │
│                            gRPC :18000                      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼  (Envoy ADS / gRPC streaming)
┌─────────────────────────────────────────────────────────────┐
│                        DATA PLANE                           │
│                                                             │
│  NLB ──▶ Envoy Proxy Fleet (Auto-Scaling Group)            │
│           ├── Auth Sidecar (Rust)                           │
│           ├── Rate Limit Sidecar (Go)                       │
│           └── Observability Sidecar (Python)                │
│                     │                                       │
│                     ▼                                       │
│              Backend Services                               │
└─────────────────────────────────────────────────────────────┘
```

## Component Details

### Broker API (`broker/`)

The entry point for all provisioning requests. Implements the Open Service Broker API spec.

- **Language**: Python 3.11 (FastAPI)
- **Auth**: API key + JWT bearer tokens
- **Storage**: DynamoDB for instance state
- **Queue**: SQS for async task dispatch
- **Endpoints**: `/v2/catalog`, `/v2/service_instances/{id}`, `/health`, `/metrics`

### Worker (`worker/`)

Processes provisioning tasks asynchronously from the SQS queue.

- **Language**: Python 3.11
- **Provisioners**: DNS (Route 53), CDN (CloudFront), Storage (S3), Load Balancer (ELBv2)
- **Workflow**: DNS → CDN → Store Context → Notify Control Plane → Mark Active

### Control Plane (`control-plane/`)

Generates and serves Envoy configurations via the xDS (Aggregated Discovery Service) protocol.

- **Language**: Python 3.11 (FastAPI + gRPC)
- **Templates**: Jinja2 → Envoy Listener, Cluster, Route, VirtualHost
- **Cache**: In-memory with TTL, backed by S3
- **Protocol**: gRPC streaming (ADS) on port 18000

### Sidecars

| Sidecar | Language | Port | Purpose |
|---------|----------|------|---------|
| Auth | Rust (Axum) | 8081 | JWT/mTLS validation, JWKS caching |
| Rate Limit | Go (gorilla/mux) | 8082 | Sliding-window rate limiting |
| Observability | Python (Flask) | 8083 | Metrics aggregation, log shipping |

### Data Flow

1. Developer applies YAML config via CLI or Git push
2. Broker validates, stores state in DynamoDB, queues task to SQS
3. Worker picks up task, provisions DNS/CDN/LB, stores context in S3
4. Worker notifies Control Plane to reload
5. Control Plane renders Jinja2 templates into Envoy config
6. Envoy proxy fleet receives config via gRPC ADS stream (< 5s)
7. Traffic flows: Client → NLB → Envoy → Sidecars → Backend

## Infrastructure

### AWS Resources

| Resource | Service | Purpose |
|----------|---------|---------|
| VPC | Networking | Multi-AZ with public/private subnets |
| EC2 ASG | Compute | Envoy proxy fleet (c6i.xlarge) |
| ECS Fargate | Compute | Broker, Worker, Control Plane |
| DynamoDB | Database | Instance state (PAY_PER_REQUEST) |
| SQS | Messaging | Provisioning task queue + DLQ |
| S3 | Storage | Configuration contexts, Terraform state |
| Route 53 | DNS | Automated DNS record management |
| CloudFront | CDN | Enterprise-plan edge caching |
| NLB | Load Balancing | L4 entry point for proxy fleet |

### Performance Targets

| Metric | SLO |
|--------|-----|
| Provisioning (p95) | < 30 seconds |
| Config propagation | < 5 seconds |
| Proxy fleet capacity | 2,000+ instances |
| Request throughput | 1M+ RPS |
| Control plane uptime | 99.99% |
| Data plane uptime | 99.999% |
