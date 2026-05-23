#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# RUVAMCO — Development Environment Bootstrap
#
# Sets up everything needed for local development:
#   • Python virtual environment
#   • CLI installation (editable)
#   • DynamoDB table creation
#   • S3 bucket creation
#   • Docker Compose stack
# ─────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()  { echo -e "${BLUE}[RUVAMCO]${NC} $*"; }
ok()   { echo -e "${GREEN}  ✓${NC} $*"; }
warn() { echo -e "${YELLOW}  ⚠${NC} $*"; }
err()  { echo -e "${RED}  ✗${NC} $*" >&2; }

# ── Prerequisite Checks ─────────────────────────────────────────

log "Checking prerequisites..."

for cmd in python3 pip3 docker docker-compose aws; do
  if command -v "$cmd" &>/dev/null; then
    ok "$cmd found: $(command -v "$cmd")"
  else
    err "$cmd not found — please install it first"
    exit 1
  fi
done

# ── Python Virtual Environment ──────────────────────────────────

log "Setting up Python virtual environment..."

cd "$ROOT_DIR"

if [ ! -d "venv" ]; then
  python3 -m venv venv
  ok "Virtual environment created"
else
  ok "Virtual environment already exists"
fi

source venv/bin/activate

pip install --upgrade pip setuptools wheel -q
pip install -r broker/requirements.txt -q
pip install -r worker/requirements.txt -q
pip install -r control-plane/requirements.txt -q
pip install -e ./cli -q
pip install pytest pytest-asyncio pytest-cov black flake8 mypy bandit -q
ok "Dependencies installed"

# ── Docker Compose ───────────────────────────────────────────────

log "Starting Docker Compose services..."

docker-compose up -d dynamodb-local elasticmq minio
ok "Infrastructure services started"

# Wait for services to be ready
log "Waiting for services to be ready..."
sleep 5

# ── DynamoDB Table ───────────────────────────────────────────────

log "Creating DynamoDB table..."

aws dynamodb create-table \
  --table-name ruvamco-instances \
  --attribute-definitions AttributeName=instance_id,AttributeType=S \
  --key-schema AttributeName=instance_id,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --endpoint-url http://localhost:8000 \
  --region us-east-1 \
  2>/dev/null && ok "DynamoDB table created" || ok "DynamoDB table already exists"

# ── S3 Buckets ───────────────────────────────────────────────────

log "Creating S3 buckets (MinIO)..."

for bucket in ruvamco-context ruvamco-templates; do
  aws s3 mb "s3://${bucket}" \
    --endpoint-url http://localhost:9000 \
    --region us-east-1 \
    2>/dev/null && ok "Bucket ${bucket} created" || ok "Bucket ${bucket} already exists"
done

# ── SQS Queue ────────────────────────────────────────────────────

log "Creating SQS queue (ElasticMQ)..."

aws sqs create-queue \
  --queue-name ruvamco-tasks \
  --endpoint-url http://localhost:9324 \
  --region us-east-1 \
  2>/dev/null && ok "SQS queue created" || ok "SQS queue already exists"

# ── Summary ──────────────────────────────────────────────────────

echo ""
log "🚀 Bootstrap complete!"
echo ""
echo "  Services:"
echo "    DynamoDB Local  → http://localhost:8000"
echo "    ElasticMQ (SQS) → http://localhost:9324"
echo "    MinIO (S3)      → http://localhost:9000  (admin: http://localhost:9001)"
echo ""
echo "  Next steps:"
echo "    source venv/bin/activate"
echo "    make up         # Start all services"
echo "    make test       # Run tests"
echo "    ruvamco --help  # Use the CLI"
echo ""
