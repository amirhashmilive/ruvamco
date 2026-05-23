# RUVAMCO - Self-Service Edge Proxy Platform

[![GitHub release](https://img.shields.io/github/v/release/amirhashmilive/ruvamco)](https://github.com/amirhashmilive/ruvamco/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://github.com/amirhashmilive/ruvamco/actions/workflows/ci.yml/badge.svg)](https://github.com/amirhashmilive/ruvamco/actions/workflows/ci.yml)
[![Code Coverage](https://img.shields.io/codecov/c/github/amirhashmilive/ruvamco)](https://codecov.io/gh/amirhashmilive/ruvamco)
[![Go Report Card](https://goreportcard.com/badge/github.com/amirhashmilive/ruvamco)](https://goreportcard.com/report/github.com/amirhashmilive/ruvamco)

**Ruvamco** is a production-grade, self-service edge proxy platform that enables developers to provision load balancing, edge routing, authentication, rate limiting, and observability through simple configuration files.

## 🚀 Features

- **Self-Service Provisioning**: Developers declare their routing requirements in YAML
- **Async Operations**: Non-blocking provisioning with status polling
- **Dynamic Configuration**: Real-time Envoy configuration updates without restarts
- **Multi-Cloud Ready**: Deploy across AWS, GCP, or Azure
- **Extensible Sidecars**: Pluggable authentication, rate limiting, and observability
- **High Performance**: Handle 1M+ RPS with sub-5 second config propagation
- **Developer CLI**: Simple command-line interface for managing routes
- **Built-in Observability**: Prometheus metrics, Grafana dashboards, structured logging

## 📦 Quick Start

### Prerequisites

- Docker and Docker Compose
- Python 3.11+
- AWS CLI (for cloud deployment)
- Terraform 1.5+ (for infrastructure)

### Local Development

```bash
# Clone the repository
git clone https://github.com/amirhashmilive/ruvamco.git
cd ruvamco

# Start local environment
make up

# Apply a sample configuration
ruvamco apply examples/basic-config.yaml

# Check status
ruvamco list

# View logs
ruvamco logs --tail=50

# Clean up
make down
```

### Deploy to Production

```bash
# Configure AWS credentials
export AWS_ACCESS_KEY_ID=your_key
export AWS_SECRET_ACCESS_KEY=your_secret

# Deploy infrastructure
cd terraform
terraform init
terraform plan
terraform apply

# Build and push images
make build
make push

# Deploy to Kubernetes
kubectl apply -f kubernetes/
```

## 🏗 Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    DEVELOPER WORKFLOW                       │
│  ┌──────────┐    ┌──────────┐    ┌──────────────────────┐  │
│  │ YAML     │───▶│ Git Push │───▶│ Auto-Provision       │  │
│  │ Config   │    │          │    │ (< 30 seconds)       │  │
│  └──────────┘    └──────────┘    └──────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      CONTROL PLANE                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ Broker   │─▶│ Worker   │─▶│ Control  │─▶│ Envoy    │   │
│  │ (API)    │  │ (Async)  │  │ Plane    │  │ Proxy    │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
│       │              │              │              │        │
│       ▼              ▼              ▼              ▼        │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │Database  │  │Queue     │  │Object    │  │Auto      │   │
│  │(State)   │  │(Tasks)   │  │Storage   │  │Scaling   │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                        DATA PLANE                           │
│                                                             │
│  User ──▶ CDN ──▶ NLB ──▶ ┌─────────────────────────┐     │
│                           │   Envoy Proxy Fleet      │     │
│                           │  ┌─────┐ ┌─────┐ ┌─────┐ │     │
│                           │  │Auth │ │Rate │ │Obs  │ │     │
│                           │  │Side │ │Lim  │ │Side │ │     │
│                           │  └─────┘ └─────┘ └─────┘ │     │
│                           └───────────┬─────────────┘     │
│                                       │                    │
│                                       ▼                    │
│                              Backend Services              │
└─────────────────────────────────────────────────────────────┘
```

## 📊 Performance Metrics

| Metric | Target |
|--------|--------|
| Provisioning Time (p95) | < 30 seconds |
| Config Propagation | < 5 seconds |
| Proxy Fleet Size | 2,000+ instances |
| Supported Services | 10,000+ |
| Request Throughput | 1M+ RPS |
| Control Plane Uptime | 99.99% |
| Data Plane Uptime | 99.999% |

## 🛠 Configuration Example

```yaml
# simple-config.yaml
apiVersion: ruvamco/v1
kind: EdgeRoute
metadata:
  name: my-api-route
spec:
  domain: api.mycompany.com
  backend:
    type: kubernetes
    target: my-service.default.svc.cluster.local
    port: 8080
  rateLimit:
    requestsPerSecond: 1000
    burst: 2000
  auth:
    type: jwt
    jwksUrl: https://auth.internal/.well-known/jwks.json
  timeouts:
    request: 30
    connection: 5
```

## 🔧 Development

```bash
# Setup development environment
make setup

# Run tests
make test

# Run linting
make lint

# Build all services
make build

# Generate documentation
make docs
```

## 📖 Documentation

- [Getting Started](docs/getting-started.md)
- [Architecture Deep Dive](docs/architecture.md)
- [API Reference](docs/api-reference.md)
- [Deployment Guide](docs/deployment-guide.md)
- [Operations Runbook](docs/operations-runbook.md)
- [Developer Guide](docs/developer-guide.md)

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guidelines](CONTRIBUTING.md).

## 📄 License

MIT License - see [LICENSE](LICENSE) for details

## 🙏 Acknowledgments

- Envoy Proxy for the incredible edge proxy
- Open Service Broker API specification
- Cloud Native Computing Foundation

## 📧 Contact

- **Maintainer**: Amir Hashmi
- **GitHub**: [@amirhashmilive](https://github.com/amirhashmilive)
- **Issues**: [GitHub Issues](https://github.com/amirhashmilive/ruvamco/issues)

---

**Star us on GitHub** ⭐ if you find this useful!
