#!/usr/bin/env bash
# Run after deployment, before enabling OverlayFS.
set -euo pipefail
PLV_DIR="${PLV_DIR:-/home/Piano-LED-Visualizer}"
[ "$(id -u)" -eq 0 ] || { echo 'Run with sudo' >&2; exit 1; }
[ -f "$PLV_DIR/visualizer.py" ] && [ -d "$PLV_DIR/lib" ] || exit 1
# Do not traverse symlinks or other mounted filesystems.
find "$PLV_DIR" -xdev -type d -exec chown root:root {} + -exec chmod 0755 {} +
find "$PLV_DIR" -xdev -type f -exec chown root:root {} + -exec chmod go-w {} +
chmod 0600 "$PLV_DIR/config/settings.xml"
chmod 0755 "$PLV_DIR"/scripts/*.sh
