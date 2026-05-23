#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# Install Docker CE on Amazon Linux 2023
# ─────────────────────────────────────────────────────────────────
set -euo pipefail

echo ">>> Installing Docker CE"

sudo dnf install -y docker
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -aG docker ec2-user

# Install Docker Compose plugin
sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo curl -SL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64" \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

echo ">>> Docker installed: $(docker --version)"
