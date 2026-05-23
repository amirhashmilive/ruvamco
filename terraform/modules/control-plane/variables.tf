variable "environment" { type = string }
variable "vpc_id" { type = string }
variable "private_subnet_ids" { type = list(string) }
variable "dynamodb_table" { type = string }
variable "sqs_queue_name" { type = string }
variable "s3_bucket_name" { type = string }
