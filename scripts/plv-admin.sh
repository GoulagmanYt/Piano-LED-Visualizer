#!/bin/bash
# Installed root-owned at /usr/local/sbin/plv-admin; no user-selected paths.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
unset PYTHONPATH PYTHONHOME PLV_DIR
APP=/home/Piano-LED-Visualizer
[ "$#" -eq 1 ] || { echo 'Usage: plv-admin ACTION' >&2; exit 2; }
case "$1" in
  status) exec systemctl --no-pager status visualizer.service rtpmidid.service ;;
  logs) exec journalctl --no-pager -u visualizer.service -b -n 200 ;;
  restart) exec systemctl restart visualizer.service ;;
  restart-midi) exec systemctl restart rtpmidid.service ;;
  password) exec /usr/bin/passwd plv ;;
  hotspot-password)
    /usr/bin/python3 -I "$APP/scripts/configure_installation_security.py" --set-hotspot-password
    exec systemctl restart visualizer.service
    ;;
  update) exec "$APP/.venv/bin/python" -I "$APP/scripts/reliable_update.py" --project-dir "$APP" ;;
  poweroff) exec /sbin/poweroff ;;
  reboot) exec /sbin/reboot ;;
  protection-status) exec /bin/bash "$APP/scripts/status_safe_poweroff.sh" ;;
  protection-enable) exec /bin/bash "$APP/scripts/enable_safe_poweroff.sh" --reboot ;;
  protection-disable) exec /bin/bash "$APP/scripts/disable_safe_poweroff.sh" --reboot ;;
  *) echo 'Unknown PLV administration action' >&2; exit 2 ;;
esac
