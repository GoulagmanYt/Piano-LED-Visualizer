#!/usr/bin/env bash
# ==============================================================================
# Piano-LED-Visualizer : Enable Safe Power Off (OverlayFS Protection)
# ==============================================================================
# Protects the SD card against corruption by mounting the root filesystem
# (rootfs) read-only with a volatile layer in RAM (tmpfs).
# Reduces power-loss risk; a clean shutdown is still preferable.
# ==============================================================================
set -euo pipefail

run_cmd() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  else
    sudo "$@"
  fi
}

echo "=== Piano-LED-Visualizer : Safe Power Off (OverlayFS) ==="

# Check if overlayroot is installed
if ! dpkg -s overlayroot >/dev/null 2>&1; then
  echo "[1/3] Installing the overlayroot package..."
  run_cmd apt-get update -qq
  run_cmd apt-get install -y overlayroot
else
  echo "[1/3] overlayroot is already installed."
fi

# Check current configuration
if [ "$(run_cmd raspi-config nonint get_overlay_conf 2>/dev/null)" = "0" ]; then
  echo "[2/3] Safe Power Off (OverlayFS) is already configured for the next boot."
else
  echo "[2/3] Enabling OverlayFS mode..."
  run_cmd raspi-config nonint enable_overlayfs
  echo "      -> OverlayFS configured successfully."
fi

echo "[3/3] System status:"
if [ "$(run_cmd raspi-config nonint get_overlay_now)" = "0" ]; then
  if [ "$(run_cmd raspi-config nonint get_bootro_conf)" != "0" ]; then
    echo "The boot partition is not protected. Disable OverlayFS, reboot, then enable protection again."
    exit 1
  fi
else
  run_cmd raspi-config nonint enable_bootro
fi
if [ "$(run_cmd raspi-config nonint get_overlay_now 2>/dev/null)" = "0" ]; then
  echo "      -> OverlayFS protection: ACTIVE (read-only / volatile RAM)"
else
  echo "      -> OverlayFS protection: REBOOT REQUIRED (active at the next boot)"
fi

echo ""
echo "----------------------------------------------------------------------"
echo "INFO: After reboot, OverlayFS protects the root filesystem and boot is read-only."
echo "      A clean shutdown is still preferable; this cannot guarantee protection against hardware failure."
echo "      All root filesystem changes will be temporary and stored in RAM."
echo "      To change settings permanently or install an update,"
echo "      use: ./scripts/disable_safe_poweroff.sh"
echo "----------------------------------------------------------------------"

if [ "${1:-}" = "--reboot" ] || [ "${1:-}" = "-r" ]; then
  echo "Immediate reboot requested..."
  run_cmd reboot
elif [ -t 0 ]; then
  read -r -p "Reboot the piano now? [y/N] " response
  if [[ "$response" =~ ^([yYoO])+$ ]]; then
    echo "Rebooting..."
    run_cmd reboot
  else
    echo "Reboot (sudo reboot) to activate protection."
  fi
fi
