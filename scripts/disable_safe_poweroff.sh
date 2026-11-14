#!/usr/bin/env bash
# ==============================================================================
# Piano-LED-Visualizer : Disable Safe Power Off (Read-Write Mode)
# ==============================================================================
# Disables OverlayFS protection to allow permanent changes
# (updates, new MIDI files and persistent settings).
# ==============================================================================
set -euo pipefail

run_cmd() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  else
    sudo "$@"
  fi
}

echo "=== Piano-LED-Visualizer: Disable Safe Power Off ==="

if [ "$(run_cmd raspi-config nonint get_overlay_conf 2>/dev/null)" = "1" ]; then
  echo "[1/2] OverlayFS is already disabled for the next boot."
else
  echo "[1/2] Disabling OverlayFS mode..."
  run_cmd raspi-config nonint disable_overlayfs
  echo "      -> Read-write mode configured for the next boot."
fi

echo "[2/2] Current system status:"
if [ "$(run_cmd raspi-config nonint get_overlay_now 2>/dev/null)" = "0" ]; then
  echo "      -> The system is currently using OverlayFS (read-only)."
  echo "         A reboot is required to return to read-write mode."
  echo "         Run this script again after reboot to make the boot partition writable too."
else
  run_cmd raspi-config nonint disable_bootro
  boot_path=/boot/firmware
  mountpoint -q "$boot_path" || boot_path=/boot
  run_cmd mount -o remount,rw "$boot_path"
  echo "      -> The system is currently in standard read-write mode."
fi

echo ""
echo "----------------------------------------------------------------------"
echo "INFO: After reboot, the system will be in standard read-write mode."
echo "      Remember to enable Safe Power Off again before unplugging the piano:"
echo "       ./scripts/enable_safe_poweroff.sh"
echo "----------------------------------------------------------------------"

if [ "${1:-}" = "--reboot" ] || [ "${1:-}" = "-r" ]; then
  echo "Immediate reboot requested..."
  run_cmd reboot
elif [ -t 0 ]; then
  read -r -p "Reboot the piano now to return to read-write mode? [y/N] " response
  if [[ "$response" =~ ^([yYoO])+$ ]]; then
    echo "Rebooting..."
    run_cmd reboot
  else
    echo "Reboot (sudo reboot) to activate read-write mode."
  fi
fi
