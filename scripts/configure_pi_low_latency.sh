#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PLV_DIR="${PLV_DIR:-$PROJECT_ROOT}"
STAMP="$(date +%Y%m%d-%H%M%S)"

run() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  else
    sudo -n "$@"
  fi
}

unit_exists() {
  systemctl list-unit-files "$1" --no-legend --no-pager 2>/dev/null | grep -q .
}

backup_file() {
  local path="$1"
  if [ -e "$path" ]; then
    run cp -a "$path" "${path}.bak-lowlatency-${STAMP}"
  fi
}

echo "Applying PLV low-latency runtime tuning..."

run install -m 0755 /dev/stdin /usr/local/sbin/plv-lowlatency-apply.sh <<'EOF'
#!/usr/bin/env bash
set -u

for governor in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
  [ -e "$governor" ] || continue
  dir=$(dirname "$governor")
  available=$(cat "$dir/scaling_available_governors" 2>/dev/null || true)
  if echo "$available" | grep -qw performance; then
    echo performance > "$governor" 2>/dev/null || true
  elif echo "$available" | grep -qw schedutil; then
    echo schedutil > "$governor" 2>/dev/null || true
  fi
done

if command -v iw >/dev/null 2>&1; then
  for iface in $(iw dev 2>/dev/null | awk '$1 == "Interface" {print $2}'); do
    iw dev "$iface" set power_save off 2>/dev/null || true
  done
fi

if command -v vcgencmd >/dev/null 2>&1; then
  vcgencmd get_throttled || true
fi
EOF

run install -d /etc/systemd/system
run install -m 0644 /dev/stdin /etc/systemd/system/plv-lowlatency.service <<'EOF'
[Unit]
Description=Piano LED Visualizer low-latency tuning
After=local-fs.target
Before=visualizer.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/plv-lowlatency-apply.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

echo "Configuring visualizer.service override for instant boot and real-time scheduling..."
OVERRIDE_DIR="/etc/systemd/system/visualizer.service.d"
OVERRIDE_FILE="${OVERRIDE_DIR}/override.conf"
run install -d "$OVERRIDE_DIR"
backup_file "$OVERRIDE_FILE"
run install -m 0644 /dev/stdin "$OVERRIDE_FILE" <<EOF
[Unit]
After=local-fs.target plv-lowlatency.service
Wants=plv-lowlatency.service

[Service]
WorkingDirectory=${PLV_DIR}/
ExecStart=
ExecStart=/usr/bin/python3 ${PLV_DIR}/visualizer.py
ExecStopPost=
ExecStopPost=/usr/bin/python3 ${PLV_DIR}/scripts/clear_leds.py
TimeoutStopSec=15
Restart=always
RestartSec=1
User=root
Group=root
SupplementaryGroups=audio gpio spi i2c video input render
UMask=0002
Nice=-10
IOSchedulingClass=realtime
IOSchedulingPriority=0
CPUSchedulingPolicy=other
CPUSchedulingPriority=0
LimitRTPRIO=10
LimitNICE=-10
LimitMEMLOCK=64M
EOF

echo "Disabling reversible background and boot-delaying services for Fast Boot..."
for unit in bluetooth.service ModemManager.service triggerhappy.service triggerhappy.socket \
            apt-daily.timer apt-daily-upgrade.timer \
            NetworkManager-wait-online.service keyboard-setup.service rpc-statd-notify.service e2scrub_reap.service; do
  if unit_exists "$unit"; then
    run systemctl disable --now "$unit" 2>/dev/null || run systemctl disable "$unit" 2>/dev/null || true
  fi
done

echo "Configuring Fast Boot parameters in config.txt..."
BOOT_CONFIG="/boot/firmware/config.txt"
[ -f "$BOOT_CONFIG" ] || BOOT_CONFIG="/boot/config.txt"
if [ -f "$BOOT_CONFIG" ]; then
  backup_file "$BOOT_CONFIG"
  run sed -i 's/^\[all\]initial_turbo=/[all]\ninitial_turbo=/' "$BOOT_CONFIG"
  # Turbo clock at 1000MHz for the first 30 seconds of boot
  if ! grep -q "^initial_turbo=" "$BOOT_CONFIG"; then
    printf '\n[all]\ninitial_turbo=30\n' | run tee -a "$BOOT_CONFIG" >/dev/null
  fi
  # Disable rainbow splash screen delay
  if ! grep -q "^disable_splash=" "$BOOT_CONFIG"; then
    echo "disable_splash=1" | run tee -a "$BOOT_CONFIG" >/dev/null
  fi
  # Disable boot delay
  if ! grep -q "^boot_delay=" "$BOOT_CONFIG"; then
    echo "boot_delay=0" | run tee -a "$BOOT_CONFIG" >/dev/null
  fi
fi

# Make helper scripts executable
if [ -d "${PLV_DIR}/scripts" ]; then
  run chmod +x "${PLV_DIR}/scripts"/*.sh 2>/dev/null || true
fi

echo "Disabling NetworkManager Wi-Fi power save..."
run install -d /etc/NetworkManager/conf.d
run install -m 0644 /dev/stdin /etc/NetworkManager/conf.d/30-wifi-powersave-off.conf <<'EOF'
[connection]
wifi.powersave=2
EOF

echo "Removing obsolete reliable_midi enable/required flags from PLV XML config..."
if [ -d "${PLV_DIR}/config" ]; then
  for xml in "${PLV_DIR}/config/settings.xml" "${PLV_DIR}/config/default_settings.xml"; do
    [ -f "$xml" ] || continue
    run python3 - "$xml" "$STAMP" <<'PY'
import shutil
import sys
import xml.etree.ElementTree as ET

path = sys.argv[1]
stamp = sys.argv[2]
tree = ET.parse(path)
root = tree.getroot()
changed = False
for tag in ("reliable_midi_enabled", "reliable_midi_required"):
    elem = root.find(tag)
    if elem is not None:
        root.remove(elem)
        changed = True
for tag, value in (("reliable_midi_host", "oscmidi-rtp.local"), ("reliable_midi_port", "5056")):
    elem = root.find(tag)
    if elem is None:
        elem = ET.SubElement(root, tag)
        changed = True
    if not (elem.text or "").strip():
        elem.text = value
        changed = True
    elif tag == "reliable_midi_port" and (elem.text or "").strip() == "5004":
        elem.text = value
        changed = True
if changed:
    shutil.copy2(path, f"{path}.bak-lowlatency-{stamp}")
    tree.write(path)
else:
    print(f"{path}: reliable MIDI defaults already current")
PY
  done
fi

echo "Cleaning safe caches..."
run apt-get clean || true
run journalctl --vacuum-size=16M || true
run find /tmp -mindepth 1 -maxdepth 1 -mtime +1 -exec rm -rf -- {} + 2>/dev/null || true

echo "Reloading systemd and applying boot tuning..."
run python3 "${PLV_DIR}/scripts/configure_service_safety.py"
run systemctl daemon-reload
run systemctl enable plv-lowlatency.service
run systemctl start plv-lowlatency.service

echo "Restarting visualizer.service with validation..."
run systemctl restart visualizer.service
sleep 3
if ! systemctl is-active --quiet visualizer.service; then
  echo "visualizer.service failed after low-latency override; leaving backups in place and printing status." >&2
  systemctl status visualizer.service --no-pager >&2 || true
  exit 1
fi

echo "Low-latency configuration applied."
systemctl is-active visualizer.service
systemctl is-enabled plv-lowlatency.service
for governor in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
  [ -e "$governor" ] && printf '%s=%s\n' "$governor" "$(cat "$governor")"
done
command -v vcgencmd >/dev/null 2>&1 && vcgencmd get_throttled || true
