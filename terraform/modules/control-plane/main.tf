# ─────────────────────────────────────────────────────────────────
# RUVAMCO — Control Plane Module
# ECS Fargate services for broker, worker, and control-plane
# ─────────────────────────────────────────────────────────────────

resource "aws_ecs_cluster" "main" {
  name = "${var.environment}-ruvamco-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = { Name = "${var.environment}-ruvamco-ecs" }
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name       = aws_ecs_cluster.main.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
    base              = 1
  }
}

# ── IAM ──────────────────────────────────────────────────────────

resource "aws_iam_role" "ecs_task_execution" {
  name = "${var.environment}-ruvamco-ecs-exec-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_exec" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "ecs_task" {
  name = "${var.environment}-ruvamco-ecs-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "ecs_task" {
  name = "${var.environment}-ruvamco-ecs-task-policy"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["dynamodb:*"]
        Resource = "arn:aws:dynamodb:*:*:table/${var.dynamodb_table}"
      },
      {
        Effect   = "Allow"
        Action   = ["sqs:*"]
        Resource = "arn:aws:sqs:*:*:${var.sqs_queue_name}"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:*"]
        Resource = ["arn:aws:s3:::${var.s3_bucket_name}", "arn:aws:s3:::${var.s3_bucket_name}/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["route53:*", "cloudfront:*", "elasticloadbalancing:*"]
        Resource = "*"
      }
    ]
  })
}

# ── Security Group ───────────────────────────────────────────────

resource "aws_security_group" "ecs" {
  name_prefix = "${var.environment}-ruvamco-ecs-"
  vpc_id      = var.vpc_id

  ingress {
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
    description = "HTTP API"
  }

  ingress {
    from_port   = 18000
    to_port     = 18000
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
    description = "gRPC xDS"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.environment}-ruvamco-ecs-sg" }
}

# ── CloudWatch Log Groups ───────────────────────────────────────

resource "aws_cloudwatch_log_group" "broker" {
  name              = "/ruvamco/${var.environment}/broker"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/ruvamco/${var.environment}/worker"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "control_plane" {
  name              = "/ruvamco/${var.environment}/control-plane"
  retention_in_days = 30
}
