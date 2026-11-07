"""Exercise installer command selection without modifying the host."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def installer_function(name):
    script = (ROOT / 'autoinstall.sh').read_text()
    match = re.search(r'^' + name + r'\(\) \{.*?^\}', script, re.M | re.S)
    assert match, name
    return match.group(0)


def run_installer_function(name, os_name, arch):
    harness = f'''set -euo pipefail
PLV_OS={os_name}
PLV_ARCH={arch}
execute_command() {{ echo "COMMAND:$1"; }}
id() {{ return 0; }}
{installer_function(name)}
{name}
'''
    import shutil
    bash = shutil.which('bash') or r'C:\Program Files\Git\bin\bash.exe'
    return subprocess.run([bash, '-c', harness], check=True, text=True, capture_output=True).stdout


def test_package_selection_for_bookworm_and_trixie():
    bookworm = run_installer_function('install_packages', 'bookworm', 'armhf')
    trixie = run_installer_function('install_packages', 'trixie', 'arm64')
    assert 'libasound2t64' in trixie and 'libfmt-dev' in trixie
    assert 'libatlas-base-dev' not in trixie
    assert 'libasound2 ' in bookworm and 'libatlas-base-dev' in bookworm
    assert 'python3-venv' in trixie and 'python3-venv' in bookworm


def test_rtpmidi_selection_for_trixie_architectures():
    arm64 = run_installer_function('install_rtpmidi_server', 'trixie', 'arm64')
    armhf = run_installer_function('install_rtpmidi_server', 'trixie', 'armhf')
    assert 'rtpmidid-debian-trixie-arm64-26.01.deb' in arm64
    assert 'git clone --depth 1 --branch v26.01' in armhf
    assert 'cmake --build' in armhf
    assert 'rtpmidid-debian-trixie-arm64' not in armhf


def test_rtpmidi_bookworm_uses_native_architecture():
    commands = run_installer_function('install_rtpmidi_server', 'bookworm', 'arm64')
    assert 'dpkg --add-architecture' not in commands
    assert 'rtpmidid_24.12.2_arm64.deb' in commands
    assert 'rtpmidid_24.12.2_armhf.deb' in run_installer_function('install_rtpmidi_server', 'bookworm', 'armhf')


def test_service_and_tuning_use_venv_interpreter():
    service = (ROOT / 'systemd/visualizer.service').read_text()
    tune = (ROOT / 'scripts/configure_pi_low_latency.sh').read_text()
    safety = (ROOT / 'scripts/configure_service_safety.py').read_text()
    assert 'ExecStart=/home/Piano-LED-Visualizer/.venv/bin/python ' in service
    assert 'ExecStart=${PYTHON} ${PLV_DIR}/visualizer.py' in tune
    assert 'ExecStopPost=${PYTHON} ${PLV_DIR}/scripts/clear_leds.py' in tune
    assert "project / '.venv/bin/python'" in safety


def test_new_install_does_not_create_mesh_system_service():
    script = (ROOT / 'autoinstall.sh').read_text()
    assert 'configure_autoconnect_script' not in script
    assert '33-midiusb.rules' not in script
    assert '/usr/local/bin/connectall.py' not in script
