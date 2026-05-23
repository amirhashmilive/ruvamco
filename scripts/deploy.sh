#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# RUVAMCO — Production Deployment Script
#
# Deploys the RUVAMCO platform to AWS:
#   1. Build & push Docker images to ECR
#   2. Run Terraform to provision infrastructure
#   3. Deploy Kubernetes manifests
#   4. Run smoke tests
# ─────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

ENVIRONMENT="${ENVIRONMENT:-production}"
AWS_REGION="${AWS_REGION:-us-east-1}"
ECR_REGISTRY="${ECR_REGISTRY:-}"
VERSION="${VERSION:-$(git -C "$ROOT_DIR" rev-parse --short HEAD)}"

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

log()  { echo -e "${BLUE}[DEPLOY]${NC} $*"; }
ok()   { echo -e "${GREEN}  ✓${NC} $*"; }
err()  { echo -e "${RED}  ✗${NC} $*" >&2; exit 1; }

# ── Preflight Checks ────────────────────────────────────────────

log "=== RUVAMCO Deployment — ${ENVIRONMENT} ==="
log "Version: ${VERSION}"
log "Region:  ${AWS_REGION}"

for cmd in docker aws terraform kubectl; do
  command -v "$cmd" &>/dev/null || err "$cmd not found"
done

# Verify AWS credentials
aws sts get-caller-identity &>/dev/null || err "AWS credentials not configured"
ok "AWS credentials verified"

# ── Step 1: Build & Push Docker Images ───────────────────────────

log "Building Docker images..."

SERVICES=("broker" "worker" "control-plane")

for svc in "${SERVICES[@]}"; do
  log "  Building ${svc}..."
  DIR_NAME="${svc}"
  if [ "$svc" = "control-plane" ]; then
    DIR_NAME="control_plane"
  fi
  docker build \
    -t "ruvamco/${svc}:${VERSION}" \
    -t "ruvamco/${svc}:latest" \
    -f "${ROOT_DIR}/${DIR_NAME}/Dockerfile" \
    "${ROOT_DIR}/${DIR_NAME}"
  ok "${svc} built"
done

if [ -n "$ECR_REGISTRY" ]; then
  log "Pushing images to ECR..."
  aws ecr get-login-password --region "$AWS_REGION" | \
    docker login --username AWS --password-stdin "$ECR_REGISTRY"

  for svc in "${SERVICES[@]}"; do
    docker tag "ruvamco/${svc}:${VERSION}" "${ECR_REGISTRY}/ruvamco/${svc}:${VERSION}"
    docker tag "ruvamco/${svc}:latest" "${ECR_REGISTRY}/ruvamco/${svc}:latest"
    docker push "${ECR_REGISTRY}/ruvamco/${svc}:${VERSION}"
    docker push "${ECR_REGISTRY}/ruvamco/${svc}:latest"
    ok "${svc} pushed to ECR"
  done
fi

# ── Step 2: Terraform Infrastructure ────────────────────────────

log "Deploying infrastructure with Terraform..."

cd "${ROOT_DIR}/terraform"

terraform init -input=false
terraform plan -input=false -out=tfplan \
  -var="environment=${ENVIRONMENT}" \
  -var="aws_region=${AWS_REGION}"

log "Applying Terraform plan..."
terraform apply -input=false tfplan
ok "Infrastructure deployed"

cd "$ROOT_DIR"

# ── Step 3: Kubernetes Deployment ────────────────────────────────

log "Deploying to Kubernetes..."

kubectl apply -f kubernetes/namespace.yaml
kubectl apply -f kubernetes/configmap.yaml
kubectl apply -f kubernetes/secrets.yaml
kubectl apply -f kubernetes/deployment.yaml
kubectl apply -f kubernetes/service.yaml
kubectl apply -f kubernetes/ingress.yaml
kubectl apply -f kubernetes/hpa.yaml

ok "Kubernetes manifests applied"

# Wait for rollout
log "Waiting for rollout..."
for deploy in ruvamco-broker ruvamco-worker ruvamco-control-plane; do
  kubectl rollout status deployment/"${deploy}" -n ruvamco --timeout=300s
  ok "${deploy} rolled out"
done

# ── Step 4: Smoke Tests ─────────────────────────────────────────

log "Running smoke tests..."

BROKER_ENDPOINT=$(kubectl get ingress ruvamco-broker -n ruvamco -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "localhost:8080")

for endpoint in "/health" "/v2/catalog"; do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://${BROKER_ENDPOINT}${endpoint}" \
    -H "X-Broker-API-Key: ${RUVAMCO_API_KEY:-dev-api-key-change-me}" || echo "000")
  if [ "$STATUS" = "200" ]; then
    ok "GET ${endpoint} → ${STATUS}"
  else
    err "GET ${endpoint} → ${STATUS} (expected 200)"
  fi
done

# ── Done ─────────────────────────────────────────────────────────

echo ""
log "🚀 Deployment complete!"
log "  Environment: ${ENVIRONMENT}"
log "  Version:     ${VERSION}"
log "  Broker:      http://${BROKER_ENDPOINT}"
echo ""
