#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_PATH=/etc/systemd/system/luckrobot-display.service
ACTION="${1:-install}"

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "Run with sudo: sudo bash scripts/install_display_service.sh [$ACTION]" >&2
  exit 1
fi

if [[ "$ACTION" == "remove" ]]; then
  systemctl disable --now luckrobot-display.service 2>/dev/null || true
  rm -f "$SERVICE_PATH"
  systemctl daemon-reload
  bash "$ROOT/scripts/manage_fbconsole.sh" attach || true
  systemctl unmask --runtime getty@tty1.service 2>/dev/null || true
  systemctl start getty@tty1.service 2>/dev/null || true
  echo "Removed luckrobot-display.service and restored framebuffer console."
  exit 0
fi
if [[ "$ACTION" != "install" ]]; then
  echo "Usage: sudo bash scripts/install_display_service.sh [install|remove]" >&2
  exit 2
fi

cat > "$SERVICE_PATH" <<EOF
[Unit]
Description=LuckRobot exclusive Qt framebuffer display
After=local-fs.target
Conflicts=getty@tty1.service

[Service]
Type=simple
User=jetson
Group=jetson
SupplementaryGroups=video input
WorkingDirectory=$ROOT
Environment=HOME=/home/jetson
ExecStartPre=+/usr/bin/bash $ROOT/scripts/manage_fbconsole.sh detach
ExecStart=/usr/bin/bash $ROOT/scripts/run_display_qt.sh
ExecStopPost=+/usr/bin/bash $ROOT/scripts/manage_fbconsole.sh attach
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now luckrobot-display.service
echo "Installed and started luckrobot-display.service for $ROOT"
