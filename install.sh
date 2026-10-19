#!/usr/bin/env bash
# Install Vitals as a systemd user service. Idempotent.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT="$UNIT_DIR/vitals.service"

command -v python3 >/dev/null || { echo "python3 is required"; exit 1; }
[ -d /proc ] || { echo "this tool needs /proc (Linux)"; exit 1; }

mkdir -p "$UNIT_DIR"
sed "s|%h/Projects/vitals|$HERE|g" "$HERE/systemd/vitals.service" > "$UNIT"

systemctl --user daemon-reload
systemctl --user enable --now vitals.service
sleep 1

if systemctl --user is-active --quiet vitals.service; then
  echo "Vitals is running: http://127.0.0.1:8791"
  echo "  logs:    journalctl --user -u vitals -f"
  echo "  stop:    systemctl --user stop vitals"
  echo "  disable: systemctl --user disable --now vitals"
else
  echo "Vitals failed to start. Check: journalctl --user -u vitals -n 40"
  exit 1
fi
