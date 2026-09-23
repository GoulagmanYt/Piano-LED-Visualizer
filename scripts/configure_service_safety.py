#!/usr/bin/env python3
"""Install the LED fail-safe and remove obsolete network boot dependencies."""
from pathlib import Path
import shutil
import time


def remove_network_dependencies(text):
    lines = []
    for line in text.splitlines():
        if line.startswith(('After=', 'Wants=')):
            key, value = line.split('=', 1)
            value = ' '.join(v for v in value.split() if v not in {
                'network-online.target', 'NetworkManager.service', 'wpa_supplicant.service'})
            if not value:
                continue
            line = key + '=' + value
        lines.append(line)
    return '\n'.join(lines) + '\n'


def write_backup(path, text):
    if path.exists():
        shutil.copy2(path, str(path) + '.bak-' + time.strftime('%Y%m%d-%H%M%S'))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


if __name__ == '__main__':
    project = Path(__file__).resolve().parents[1]
    target = Path('/etc/systemd/system/visualizer.service')
    source = target if target.exists() else Path('/lib/systemd/system/visualizer.service')
    # Ordering dependencies cannot be removed by an empty drop-in assignment.
    write_backup(target, remove_network_dependencies(source.read_text()))
    override = Path('/etc/systemd/system/visualizer.service.d/zz-safety.conf')
    write_backup(override, '[Service]\nExecStopPost=\n'
                 f'ExecStopPost=/usr/bin/python3 {project}/scripts/clear_leds.py\n'
                 'TimeoutStopSec=15\nUMask=0022\n'
                 'CPUSchedulingPolicy=other\nCPUSchedulingPriority=0\n')
    tuning = Path('/etc/systemd/system/plv-lowlatency.service')
    if tuning.exists():
        write_backup(tuning, remove_network_dependencies(tuning.read_text()))
