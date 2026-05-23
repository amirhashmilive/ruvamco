# ─────────────────────────────────────────────────────────────────
# RUVAMCO — Packer Image for Envoy Proxy Nodes
#
# Builds a hardened Amazon Linux 2023 AMI with:
#   • Docker CE + containerd
#   • Envoy Proxy v1.28
#   • CIS Benchmark hardening
#   • CloudWatch agent
#   • SSM agent
# ─────────────────────────────────────────────────────────────────

packer {
  required_plugins {
    amazon = {
      version = ">= 1.3.0"
      source  = "github.com/hashicorp/amazon"
    }
    ansible = {
      version = ">= 1.1.0"
      source  = "github.com/hashicorp/ansible"
    }
  }
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "instance_type" {
  type    = string
  default = "c6i.large"
}

variable "ami_name_prefix" {
  type    = string
  default = "ruvamco-proxy"
}

variable "envoy_version" {
  type    = string
  default = "1.28.1"
}

source "amazon-ebs" "proxy" {
  ami_name      = "${var.ami_name_prefix}-{{timestamp}}"
  instance_type = var.instance_type
  region        = var.aws_region

  source_ami_filter {
    filters = {
      name                = "al2023-ami-2023.*-x86_64"
      root-device-type    = "ebs"
      virtualization-type = "hvm"
    }
    most_recent = true
    owners      = ["amazon"]
  }

  ssh_username = "ec2-user"

  tags = {
    Name        = "${var.ami_name_prefix}-{{timestamp}}"
    Project     = "ruvamco"
    Builder     = "packer"
    EnvoyVersion = var.envoy_version
  }

  launch_block_device_mappings {
    device_name           = "/dev/xvda"
    volume_size           = 30
    volume_type           = "gp3"
    iops                  = 3000
    throughput            = 125
    delete_on_termination = true
    encrypted             = true
  }
}

build {
  sources = ["source.amazon-ebs.proxy"]

  provisioner "shell" {
    scripts = [
      "scripts/install-docker.sh",
      "scripts/install-envoy.sh",
      "scripts/harden.sh",
    ]
    environment_vars = [
      "ENVOY_VERSION=${var.envoy_version}",
    ]
  }

  provisioner "ansible" {
    playbook_file = "ansible/playbook.yml"
  }

  post-processor "manifest" {
    output     = "manifest.json"
    strip_path = true
  }
}
