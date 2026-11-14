#!/usr/bin/env bash
# Run after deployment, before enabling OverlayFS.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PLV_DIR="${PLV_DIR:-$PROJECT_ROOT}"
[ "$(id -u)" -eq 0 ] || { echo 'Run with sudo' >&2; exit 1; }
[ -f "$PLV_DIR/visualizer.py" ] && [ -d "$PLV_DIR/lib" ] || exit 1
# Do not traverse symlinks or other mounted filesystems.
find "$PLV_DIR" -xdev -type d -exec chown root:root {} + -exec chmod 0755 {} +
find "$PLV_DIR" -xdev -type f -exec chown root:root {} + -exec chmod go-w {} +
[ ! -f "$PLV_DIR/config/settings.xml" ] || chmod 0600 "$PLV_DIR/config/settings.xml"
chmod 0755 "$PLV_DIR"/scripts/*.sh
python3 "$PLV_DIR/scripts/configure_installation_security.py" "$@"
