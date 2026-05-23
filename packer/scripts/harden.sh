#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# CIS Benchmark hardening for RUVAMCO proxy instances
# ─────────────────────────────────────────────────────────────────
set -euo pipefail

echo ">>> Applying CIS hardening"

# Disable unused filesystems
for fs in cramfs freevxfs jffs2 hfs hfsplus squashfs udf; do
  echo "install ${fs} /bin/true" | sudo tee -a /etc/modprobe.d/disable-filesystems.conf
done

# Kernel hardening via sysctl
cat <<'EOF' | sudo tee /etc/sysctl.d/99-ruvamco-hardening.conf
# Network security
net.ipv4.ip_forward = 0
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.default.send_redirects = 0
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv4.conf.all.log_martians = 1
net.ipv4.conf.default.log_martians = 1
net.ipv4.icmp_echo_ignore_broadcasts = 1
net.ipv4.tcp_syncookies = 1

# Performance tuning for high-throughput proxy
net.core.somaxconn = 65535
net.core.netdev_max_backlog = 65535
net.ipv4.tcp_max_syn_backlog = 65535
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_fin_timeout = 15
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 87380 16777216

# File descriptor limits
fs.file-max = 2097152
fs.nr_open = 2097152
EOF

sudo sysctl --system

# SSH hardening
sudo sed -i 's/#PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config
sudo sed -i 's/#MaxAuthTries 6/MaxAuthTries 3/' /etc/ssh/sshd_config
sudo sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo sed -i 's/X11Forwarding yes/X11Forwarding no/' /etc/ssh/sshd_config

# Set file permissions
sudo chmod 600 /etc/ssh/sshd_config
sudo chmod 644 /etc/passwd
sudo chmod 000 /etc/shadow

# Remove unnecessary packages
sudo dnf remove -y telnet rsh-server rsh || true

# Enable auditd
sudo systemctl enable auditd || true

echo ">>> Hardening complete"
