#!/usr/bin/env bash
# ==============================================================================
# Piano-LED-Visualizer : Status Safe Power Off (OverlayFS)
# ==============================================================================
set -euo pipefail

run_cmd() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  else
    sudo "$@"
  fi
}

echo "=== Piano-LED-Visualizer: Safe Power Off Status ==="

is_active=false
if [ "$(run_cmd raspi-config nonint get_overlay_now 2>/dev/null)" = "0" ]; then
  is_active=true
fi

is_conf=false
if [ "$(run_cmd raspi-config nonint get_overlay_conf 2>/dev/null)" = "0" ]; then
  is_conf=true
fi

if [ "$is_active" = "true" ]; then
  echo "Current status: [PROTECTED] The root filesystem uses OverlayFS (read-only)."
  echo "                Root filesystem writes are volatile; a clean shutdown is still preferable."
else
  echo "Current status: [READ-WRITE] The filesystem is mounted in standard read-write mode."
  echo "                WARNING: Shut down cleanly (sudo poweroff) before unplugging,"
  echo "                or enable Safe Power Off with: ./scripts/enable_safe_poweroff.sh"
fi

echo "Boot partition:"
findmnt -no TARGET,OPTIONS /boot/firmware 2>/dev/null || findmnt -no TARGET,OPTIONS /boot

if [ "$is_conf" = "true" ]; then
  echo "Next boot: Safe Power Off will be ACTIVE."
else
  echo "Next boot: Read-write mode will be ACTIVE."
fi
