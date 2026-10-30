#!/usr/bin/env bash
# sudo bash scripts/install_network_service.sh jetson wlP1p1s0
# On the cerebellum: ... nvidia wlP1p1s0. Does not activate/change any network.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OWNER="${1:?provide local UI/SSH username}"
IFACE="${2:-wlP1p1s0}"
[[ "$OWNER" =~ ^[a-z_][a-z0-9_-]*$ && "$IFACE" =~ ^[a-zA-Z0-9_-]+$ ]]
id "$OWNER" >/dev/null
[[ "$(nmcli -g GENERAL.TYPE device show "$IFACE")" == "wifi" ]]
/usr/bin/python3 -c 'import dbus'
install -d -m 755 /usr/local/lib/luckrobot
install -o root -g root -m 755 "$ROOT/edge/network/agent.py" /usr/local/lib/luckrobot/network_agent.py
cat > /etc/systemd/system/luckrobot-network.service <<EOF
[Unit]
Description=LuckRobot Wi-Fi-only network helper
After=NetworkManager.service
Requires=NetworkManager.service

[Service]
Type=simple
User=root
Group=$OWNER
UMask=0007
RuntimeDirectory=luckrobot-network
RuntimeDirectoryMode=0750
RuntimeDirectoryPreserve=restart
ExecStart=/usr/bin/python3 /usr/local/lib/luckrobot/network_agent.py --interface $IFACE
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/run/luckrobot-network
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now luckrobot-network.service
