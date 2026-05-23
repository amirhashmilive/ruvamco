# ─────────────────────────────────────────────────────────────────
# RUVAMCO — Terraform Variables
# ─────────────────────────────────────────────────────────────────

variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment (dev, staging, production)"
  type        = string
  default     = "production"

  validation {
    condition     = contains(["dev", "staging", "production"], var.environment)
    error_message = "Environment must be dev, staging, or production."
  }
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "List of availability zones"
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b", "us-east-1c"]
}

variable "private_subnet_cidrs" {
  description = "CIDR blocks for private subnets"
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for public subnets"
  type        = list(string)
  default     = ["10.0.101.0/24", "10.0.102.0/24", "10.0.103.0/24"]
}

variable "proxy_instance_type" {
  description = "EC2 instance type for Envoy proxy nodes"
  type        = string
  default     = "c6i.xlarge"
}

variable "proxy_min_size" {
  description = "Minimum number of proxy instances"
  type        = number
  default     = 3
}

variable "proxy_max_size" {
  description = "Maximum number of proxy instances"
  type        = number
  default     = 2000
}

variable "proxy_desired_capacity" {
  description = "Desired number of proxy instances"
  type        = number
  default     = 6
}

variable "proxy_ami_id" {
  description = "AMI ID for proxy instances (built with Packer)"
  type        = string
  default     = ""
}

variable "dynamodb_table_name" {
  description = "DynamoDB table for instance state"
  type        = string
  default     = "ruvamco-instances"
}

variable "sqs_queue_name" {
  description = "SQS queue for provisioning tasks"
  type        = string
  default     = "ruvamco-tasks"
}

variable "s3_context_bucket" {
  description = "S3 bucket for configuration contexts"
  type        = string
  default     = "ruvamco-context"
}
