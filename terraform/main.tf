# ─────────────────────────────────────────────────────────────────
# RUVAMCO — Root Terraform Configuration
#
# Provisions the complete RUVAMCO infrastructure on AWS:
#   • VPC with public/private subnets across 3 AZs
#   • ECS Fargate cluster for control-plane services
#   • Auto-Scaling Group of Envoy proxy instances
#   • DynamoDB, SQS, S3 for state management
#   • CloudWatch, ALB, Route 53 for operations
# ─────────────────────────────────────────────────────────────────

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket         = "ruvamco-terraform-state"
    key            = "infrastructure/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "ruvamco-terraform-locks"
    encrypt        = true
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "ruvamco"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

# ── Modules ──────────────────────────────────────────────────────

module "vpc" {
  source = "./modules/vpc"

  environment     = var.environment
  vpc_cidr        = var.vpc_cidr
  azs             = var.availability_zones
  private_subnets = var.private_subnet_cidrs
  public_subnets  = var.public_subnet_cidrs
}

module "proxy_fleet" {
  source = "./modules/proxy-fleet"

  environment       = var.environment
  vpc_id            = module.vpc.vpc_id
  private_subnet_ids = module.vpc.private_subnet_ids
  public_subnet_ids  = module.vpc.public_subnet_ids
  instance_type     = var.proxy_instance_type
  min_size          = var.proxy_min_size
  max_size          = var.proxy_max_size
  desired_capacity  = var.proxy_desired_capacity
  ami_id            = var.proxy_ami_id
}

module "control_plane" {
  source = "./modules/control-plane"

  environment        = var.environment
  vpc_id             = module.vpc.vpc_id
  private_subnet_ids = module.vpc.private_subnet_ids
  dynamodb_table     = var.dynamodb_table_name
  sqs_queue_name     = var.sqs_queue_name
  s3_bucket_name     = var.s3_context_bucket
}

# ── Shared Resources ────────────────────────────────────────────

resource "aws_dynamodb_table" "instances" {
  name         = var.dynamodb_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "instance_id"

  attribute {
    name = "instance_id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  tags = {
    Name = "${var.environment}-ruvamco-instances"
  }
}

resource "aws_sqs_queue" "provisioning_tasks" {
  name                       = var.sqs_queue_name
  visibility_timeout_seconds = 300
  message_retention_seconds  = 86400
  receive_wait_time_seconds  = 20

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 3
  })

  tags = {
    Name = "${var.environment}-ruvamco-tasks"
  }
}

resource "aws_sqs_queue" "dlq" {
  name                      = "${var.sqs_queue_name}-dlq"
  message_retention_seconds = 1209600  # 14 days

  tags = {
    Name = "${var.environment}-ruvamco-tasks-dlq"
  }
}

resource "aws_s3_bucket" "context" {
  bucket = var.s3_context_bucket

  tags = {
    Name = "${var.environment}-ruvamco-context"
  }
}

resource "aws_s3_bucket_versioning" "context" {
  bucket = aws_s3_bucket.context.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "context" {
  bucket = aws_s3_bucket.context.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}
