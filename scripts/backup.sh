#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# RUVAMCO — Backup Script
#
# Creates point-in-time backups of:
#   • DynamoDB instance state table
#   • S3 configuration contexts
#   • Terraform state
# ─────────────────────────────────────────────────────────────────
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
ENVIRONMENT="${ENVIRONMENT:-production}"
BACKUP_BUCKET="${BACKUP_BUCKET:-ruvamco-backups}"
TIMESTAMP=$(date -u +"%Y%m%dT%H%M%SZ")
BACKUP_PREFIX="backups/${ENVIRONMENT}/${TIMESTAMP}"

log() { echo "[BACKUP] $(date -u +%H:%M:%S) $*"; }

log "=== RUVAMCO Backup — ${ENVIRONMENT} ==="
log "Timestamp: ${TIMESTAMP}"

# ── DynamoDB Backup ──────────────────────────────────────────────

log "Creating DynamoDB backup..."

BACKUP_ARN=$(aws dynamodb create-backup \
  --table-name "ruvamco-instances" \
  --backup-name "ruvamco-instances-${TIMESTAMP}" \
  --region "$AWS_REGION" \
  --query 'BackupDetails.BackupArn' \
  --output text)

log "DynamoDB backup created: ${BACKUP_ARN}"

# ── S3 Context Backup ───────────────────────────────────────────

log "Syncing S3 contexts to backup bucket..."

aws s3 sync \
  "s3://ruvamco-context/contexts/" \
  "s3://${BACKUP_BUCKET}/${BACKUP_PREFIX}/contexts/" \
  --region "$AWS_REGION" \
  --sse AES256

CONTEXT_COUNT=$(aws s3 ls "s3://ruvamco-context/contexts/" --region "$AWS_REGION" | wc -l)
log "Backed up ${CONTEXT_COUNT} context files"

# ── Terraform State Backup ──────────────────────────────────────

log "Backing up Terraform state..."

aws s3 cp \
  "s3://ruvamco-terraform-state/infrastructure/terraform.tfstate" \
  "s3://${BACKUP_BUCKET}/${BACKUP_PREFIX}/terraform.tfstate" \
  --region "$AWS_REGION" \
  --sse AES256

log "Terraform state backed up"

# ── Backup Manifest ─────────────────────────────────────────────

MANIFEST=$(cat <<EOF
{
  "timestamp": "${TIMESTAMP}",
  "environment": "${ENVIRONMENT}",
  "region": "${AWS_REGION}",
  "components": {
    "dynamodb": {"backup_arn": "${BACKUP_ARN}"},
    "s3_contexts": {"count": ${CONTEXT_COUNT}},
    "terraform_state": true
  }
}
EOF
)

echo "$MANIFEST" | aws s3 cp - \
  "s3://${BACKUP_BUCKET}/${BACKUP_PREFIX}/manifest.json" \
  --region "$AWS_REGION" \
  --content-type "application/json" \
  --sse AES256

log "=== Backup complete ==="
log "Location: s3://${BACKUP_BUCKET}/${BACKUP_PREFIX}/"
