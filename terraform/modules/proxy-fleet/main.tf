# ─────────────────────────────────────────────────────────────────
# RUVAMCO — Proxy Fleet Module
# Auto-Scaling Group of Envoy proxy instances behind an NLB
# ─────────────────────────────────────────────────────────────────

resource "aws_security_group" "proxy" {
  name_prefix = "${var.environment}-ruvamco-proxy-"
  vpc_id      = var.vpc_id

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HTTPS from internet"
  }

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HTTP redirect"
  }

  ingress {
    from_port   = 9901
    to_port     = 9901
    protocol    = "tcp"
    cidr_blocks = [data.aws_vpc.selected.cidr_block]
    description = "Envoy admin (internal)"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.environment}-ruvamco-proxy-sg" }

  lifecycle { create_before_destroy = true }
}

data "aws_vpc" "selected" {
  id = var.vpc_id
}

# ── Launch Template ──────────────────────────────────────────────

resource "aws_launch_template" "proxy" {
  name_prefix   = "${var.environment}-ruvamco-proxy-"
  image_id      = var.ami_id
  instance_type = var.instance_type

  vpc_security_group_ids = [aws_security_group.proxy.id]

  iam_instance_profile {
    name = aws_iam_instance_profile.proxy.name
  }

  user_data = base64encode(templatefile("${path.module}/userdata.sh.tpl", {
    environment        = var.environment
    control_plane_addr = "control-plane.ruvamco.internal:18000"
  }))

  monitoring { enabled = true }

  tag_specifications {
    resource_type = "instance"
    tags = {
      Name = "${var.environment}-ruvamco-proxy"
      Role = "envoy-proxy"
    }
  }

  lifecycle { create_before_destroy = true }
}

# ── Auto Scaling Group ───────────────────────────────────────────

resource "aws_autoscaling_group" "proxy" {
  name                = "${var.environment}-ruvamco-proxy-asg"
  min_size            = var.min_size
  max_size            = var.max_size
  desired_capacity    = var.desired_capacity
  vpc_zone_identifier = var.private_subnet_ids
  target_group_arns   = [aws_lb_target_group.proxy.arn]
  health_check_type   = "ELB"

  launch_template {
    id      = aws_launch_template.proxy.id
    version = "$Latest"
  }

  instance_refresh {
    strategy = "Rolling"
    preferences {
      min_healthy_percentage = 90
    }
  }

  tag {
    key                 = "Name"
    value               = "${var.environment}-ruvamco-proxy"
    propagate_at_launch = true
  }
}

# ── Scaling Policies ─────────────────────────────────────────────

resource "aws_autoscaling_policy" "cpu_target" {
  name                   = "${var.environment}-ruvamco-cpu-target"
  autoscaling_group_name = aws_autoscaling_group.proxy.name
  policy_type            = "TargetTrackingScaling"

  target_tracking_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ASGAverageCPUUtilization"
    }
    target_value = 60.0
  }
}

# ── Network Load Balancer ────────────────────────────────────────

resource "aws_lb" "proxy" {
  name               = "${var.environment}-ruvamco-nlb"
  internal           = false
  load_balancer_type = "network"
  subnets            = var.public_subnet_ids

  enable_cross_zone_load_balancing = true

  tags = { Name = "${var.environment}-ruvamco-nlb" }
}

resource "aws_lb_target_group" "proxy" {
  name     = "${var.environment}-ruvamco-proxy-tg"
  port     = 443
  protocol = "TCP"
  vpc_id   = var.vpc_id

  health_check {
    protocol            = "HTTP"
    port                = "9901"
    path                = "/ready"
    interval            = 10
    healthy_threshold   = 2
    unhealthy_threshold = 2
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.proxy.arn
  port              = 443
  protocol          = "TCP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.proxy.arn
  }
}

# ── IAM ──────────────────────────────────────────────────────────

resource "aws_iam_role" "proxy" {
  name = "${var.environment}-ruvamco-proxy-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.proxy.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "proxy" {
  name = "${var.environment}-ruvamco-proxy-profile"
  role = aws_iam_role.proxy.name
}
