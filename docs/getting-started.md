# Getting Started with RUVAMCO

## Overview

RUVAMCO is a self-service edge proxy platform that lets developers provision production-grade load balancing, authentication, rate limiting, and observability through simple YAML configuration files.

This guide walks you through setting up a local development environment and provisioning your first edge route in under 5 minutes.

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Docker | 24+ | Container runtime |
| Docker Compose | 2.20+ | Local service orchestration |
| Python | 3.11+ | Broker, Worker, Control Plane |
| AWS CLI | 2.x | Cloud resource management |
| Make | 4.x | Build automation |

## Quick Start

### 1. Clone and Bootstrap

```bash
git clone https://github.com/amirhashmilive/ruvamco.git
cd ruvamco
./scripts/bootstrap.sh
```

The bootstrap script will:
- Create a Python virtual environment
- Install all dependencies
- Start local infrastructure (DynamoDB, SQS, S3)
- Create required tables and buckets
- Install the `ruvamco` CLI

### 2. Start the Platform

```bash
make up
```

This starts the complete platform:

| Service | URL | Description |
|---------|-----|-------------|
| Broker API | http://localhost:8080/docs | OpenAPI documentation |
| Control Plane | http://localhost:8081 | Configuration management |
| Envoy Admin | http://localhost:9901 | Proxy admin interface |
| Prometheus | http://localhost:9090 | Metrics |
| Grafana | http://localhost:3000 | Dashboards (admin/admin) |
| Jaeger | http://localhost:16686 | Distributed tracing |

### 3. Provision Your First Route

Create a configuration file `my-route.yaml`:

```yaml
apiVersion: ruvamco/v1
kind: EdgeRoute
metadata:
  name: my-api
  namespace: default
spec:
  domain: api.example.com
  backend:
    type: kubernetes
    target: my-service.default.svc.cluster.local
    port: 8080
  rateLimit:
    requestsPerSecond: 100
    burst: 200
  timeouts:
    request: 30
    connection: 5
```

Apply it:

```bash
ruvamco apply my-route.yaml --wait
```

### 4. Verify

```bash
# Check instance status
ruvamco status default-my-api

# List all instances
ruvamco list

# View rendered Envoy config
curl http://localhost:8081/v1/instances/default-my-api/config | jq
```

### 5. Clean Up

```bash
ruvamco delete default-my-api --force
make down
```

## What's Next?

- **[Architecture](architecture.md)** — Understand how RUVAMCO works under the hood
- **[API Reference](api-reference.md)** — Complete API documentation
- **[Deployment Guide](deployment-guide.md)** — Deploy to AWS production
- **[Developer Guide](developer-guide.md)** — Contribute to RUVAMCO
