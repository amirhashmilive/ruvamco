#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# Install Envoy Proxy
# ─────────────────────────────────────────────────────────────────
set -euo pipefail

ENVOY_VERSION="${ENVOY_VERSION:-1.28.1}"
echo ">>> Installing Envoy Proxy v${ENVOY_VERSION}"

# Install from GetEnvoy
curl -sL "https://func-e.io/install.sh" | sudo bash -s -- -b /usr/local/bin
func-e use "${ENVOY_VERSION}"
sudo cp ~/.func-e/versions/${ENVOY_VERSION}/bin/envoy /usr/local/bin/envoy
sudo chmod +x /usr/local/bin/envoy

# Create envoy user and directories
sudo useradd --system --no-create-home --shell /sbin/nologin envoy || true
sudo mkdir -p /etc/envoy /var/log/envoy /var/lib/envoy
sudo chown -R envoy:envoy /var/log/envoy /var/lib/envoy

# Install systemd service
cat <<'EOF' | sudo tee /etc/systemd/system/envoy.service
[Unit]
Description=Envoy Proxy
Documentation=https://www.envoyproxy.io/
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=envoy
Group=envoy
ExecStart=/usr/local/bin/envoy -c /etc/envoy/envoy.yaml --log-level info --log-path /var/log/envoy/envoy.log
ExecReload=/bin/kill -HUP $MAINPID
Restart=on-failure
RestartSec=5
LimitNOFILE=65536
LimitNPROC=65536

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable envoy

echo ">>> Envoy installed: $(envoy --version)"
