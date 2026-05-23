# ─────────────────────────────────────────────────────────────────
# RUVAMCO — Terraform Outputs
# ─────────────────────────────────────────────────────────────────

output "vpc_id" {
  description = "ID of the created VPC"
  value       = module.vpc.vpc_id
}

output "private_subnet_ids" {
  description = "IDs of private subnets"
  value       = module.vpc.private_subnet_ids
}

output "public_subnet_ids" {
  description = "IDs of public subnets"
  value       = module.vpc.public_subnet_ids
}

output "proxy_asg_name" {
  description = "Name of the proxy Auto Scaling Group"
  value       = module.proxy_fleet.asg_name
}

output "proxy_nlb_dns" {
  description = "DNS name of the proxy Network Load Balancer"
  value       = module.proxy_fleet.nlb_dns_name
}

output "dynamodb_table_name" {
  description = "DynamoDB table name for instance state"
  value       = aws_dynamodb_table.instances.name
}

output "sqs_queue_url" {
  description = "URL of the provisioning task queue"
  value       = aws_sqs_queue.provisioning_tasks.url
}

output "s3_context_bucket" {
  description = "S3 bucket for configuration contexts"
  value       = aws_s3_bucket.context.bucket
}
