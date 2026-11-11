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
