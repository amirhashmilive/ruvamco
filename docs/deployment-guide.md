# RUVAMCO Deployment Guide

## Overview

This guide covers deploying RUVAMCO to AWS production using Terraform, Packer, and Kubernetes.

## Prerequisites

- AWS account with admin access
- Terraform >= 1.5.0
- Packer >= 1.10.0
- kubectl configured for your cluster
- Docker >= 24.0
- S3 bucket for Terraform state

## Deployment Architecture

```
                    ┌────────────────────────────┐
                    │         Route 53           │
                    │    broker.ruvamco.io       │
                    └──────────┬─────────────────┘
                               │
                    ┌──────────▼─────────────────┐
                    │   Network Load Balancer     │
                    │   (us-east-1a/b/c)          │
                    └──────────┬─────────────────┘
                               │
          ┌────────────────────┼────────────────────┐
          ▼                    ▼                    ▼
    ┌──────────┐        ┌──────────┐        ┌──────────┐
    │ Envoy    │        │ Envoy    │        │ Envoy    │
    │ AZ-1a    │        │ AZ-1b    │        │ AZ-1c    │
    └──────────┘        └──────────┘        └──────────┘
```

## Step 1: Build AMI

```bash
cd packer/

packer init proxy-image.pkr.hcl

packer build \
  -var "aws_region=us-east-1" \
  -var "envoy_version=1.28.1" \
  proxy-image.pkr.hcl
```

Note the AMI ID from the output.

## Step 2: Configure Terraform

Create `terraform/terraform.tfvars`:

```hcl
environment        = "production"
aws_region         = "us-east-1"
proxy_ami_id       = "ami-xxxxxxxxxxxxx"  # from Step 1
proxy_min_size     = 3
proxy_desired_capacity = 6
proxy_max_size     = 100
dynamodb_table_name = "ruvamco-instances"
sqs_queue_name     = "ruvamco-tasks"
s3_context_bucket  = "ruvamco-context-prod"
```

## Step 3: Deploy Infrastructure

```bash
cd terraform/

# Initialize with S3 backend
terraform init \
  -backend-config="bucket=ruvamco-terraform-state" \
  -backend-config="region=us-east-1"

# Plan and review
terraform plan -out=tfplan

# Apply
terraform apply tfplan
```

## Step 4: Build and Push Docker Images

```bash
# Login to ECR
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin <account>.dkr.ecr.us-east-1.amazonaws.com

# Build and push
for svc in broker worker control-plane; do
  docker build -t ruvamco/${svc}:latest -f ${svc}/Dockerfile ${svc}/
  docker tag ruvamco/${svc}:latest <account>.dkr.ecr.us-east-1.amazonaws.com/ruvamco/${svc}:latest
  docker push <account>.dkr.ecr.us-east-1.amazonaws.com/ruvamco/${svc}:latest
done
```

## Step 5: Deploy to Kubernetes

```bash
# Update image references in kubernetes/deployment.yaml

kubectl apply -f kubernetes/namespace.yaml
kubectl apply -f kubernetes/configmap.yaml
kubectl apply -f kubernetes/secrets.yaml    # Update with real values first!
kubectl apply -f kubernetes/deployment.yaml
kubectl apply -f kubernetes/service.yaml
kubectl apply -f kubernetes/ingress.yaml
kubectl apply -f kubernetes/hpa.yaml

# Verify rollout
kubectl rollout status deployment/ruvamco-broker -n ruvamco --timeout=300s
```

## Step 6: Configure DNS

Point your domain to the NLB:

```bash
NLB_DNS=$(terraform output -raw proxy_nlb_dns)
echo "Create CNAME: broker.ruvamco.io → ${NLB_DNS}"
```

## Step 7: Verify

```bash
# Health check
curl https://broker.ruvamco.io/health

# Catalog
curl -H "X-Broker-API-Key: <key>" https://broker.ruvamco.io/v2/catalog
```

## Automated Deployment

Use the deployment script for a fully automated flow:

```bash
ENVIRONMENT=production \
ECR_REGISTRY=<account>.dkr.ecr.us-east-1.amazonaws.com \
./scripts/deploy.sh
```

## Rollback

```bash
# Kubernetes rollback
kubectl rollout undo deployment/ruvamco-broker -n ruvamco

# Terraform rollback
terraform apply -target=module.proxy_fleet -var="proxy_ami_id=<previous-ami>"
```
