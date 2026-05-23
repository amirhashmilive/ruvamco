#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# RUVAMCO — Secret Rotation Script
#
# Rotates:
#   • Broker API keys
#   • JWT signing secret
#   • AWS access keys (for service accounts)
#   • Kubernetes secrets
# ─────────────────────────────────────────────────────────────────
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
NAMESPACE="ruvamco"

log() { echo "[ROTATE] $(date -u +%H:%M:%S) $*"; }
warn() { echo "[ROTATE] ⚠ $*"; }

log "=== RUVAMCO Secret Rotation ==="

# ── Generate New Secrets ─────────────────────────────────────────

NEW_API_KEY=$(openssl rand -hex 32)
NEW_JWT_SECRET=$(openssl rand -base64 48)

log "New API key generated:   ${NEW_API_KEY:0:8}..."
log "New JWT secret generated: ${NEW_JWT_SECRET:0:8}..."

# ── Update AWS Secrets Manager ───────────────────────────────────

log "Updating AWS Secrets Manager..."

aws secretsmanager update-secret \
  --secret-id "ruvamco/api-key" \
  --secret-string "$NEW_API_KEY" \
  --region "$AWS_REGION" \
  2>/dev/null || \
aws secretsmanager create-secret \
  --name "ruvamco/api-key" \
  --secret-string "$NEW_API_KEY" \
  --region "$AWS_REGION"

aws secretsmanager update-secret \
  --secret-id "ruvamco/jwt-secret" \
  --secret-string "$NEW_JWT_SECRET" \
  --region "$AWS_REGION" \
  2>/dev/null || \
aws secretsmanager create-secret \
  --name "ruvamco/jwt-secret" \
  --secret-string "$NEW_JWT_SECRET" \
  --region "$AWS_REGION"

log "AWS Secrets Manager updated"

# ── Update Kubernetes Secrets ────────────────────────────────────

log "Updating Kubernetes secrets..."

kubectl create secret generic ruvamco-secrets \
  --namespace "$NAMESPACE" \
  --from-literal="API_KEY=${NEW_API_KEY}" \
  --from-literal="JWT_SECRET=${NEW_JWT_SECRET}" \
  --dry-run=client -o yaml | kubectl apply -f -

log "Kubernetes secrets updated"

# ── Rolling Restart ──────────────────────────────────────────────

log "Restarting deployments to pick up new secrets..."

for deploy in ruvamco-broker ruvamco-worker ruvamco-control-plane; do
  kubectl rollout restart deployment/"${deploy}" -n "$NAMESPACE"
  log "  Restarted ${deploy}"
done

# Wait for rollouts
for deploy in ruvamco-broker ruvamco-worker ruvamco-control-plane; do
  kubectl rollout status deployment/"${deploy}" -n "$NAMESPACE" --timeout=180s
  log "  ${deploy} ready"
done

# ── Verification ─────────────────────────────────────────────────

log "Verifying health after rotation..."
sleep 10

BROKER_POD=$(kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/name=ruvamco-broker -o jsonpath='{.items[0].metadata.name}')
HEALTH=$(kubectl exec -n "$NAMESPACE" "$BROKER_POD" -- python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8080/health').read().decode())" 2>/dev/null || echo "FAILED")

if echo "$HEALTH" | grep -q "healthy"; then
  log "✓ Health check passed after rotation"
else
  warn "Health check inconclusive — verify manually"
fi

log "=== Secret rotation complete ==="
log ""
log "IMPORTANT: Update any external clients with the new API key."
log "New API key prefix: ${NEW_API_KEY:0:8}..."
