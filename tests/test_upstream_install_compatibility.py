"""Exercise installer command selection without modifying the host."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which('bash') or r'C:\Program Files\Git\bin\bash.exe'


def installer_function(name):
    script = (ROOT / 'autoinstall.sh').read_text()
    match = re.search(r'^' + name + r'\(\) \{.*?^\}', script, re.MULTILINE | re.DOTALL)
    assert match, name
    return match.group(0)


def run_installer_function(name, os_name, arch):
    harness = f'''set -euo pipefail
PLV_OS={os_name}
PLV_ARCH={arch}
APP_DIR=/home/Piano-LED-Visualizer
execute_command() {{ echo "COMMAND:$1"; }}
id() {{ return 0; }}
{installer_function(name)}
{name}
'''
    return subprocess.run([BASH, '-c', harness], check=True, text=True, capture_output=True).stdout


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
    assert 'scripts/install_rtpmidid.py --os trixie --arch arm64' in arm64
    assert 'scripts/install_rtpmidid.py --os trixie --arch armhf' in armhf


def test_rtpmidi_bookworm_uses_native_architecture():
    commands = run_installer_function('install_rtpmidi_server', 'bookworm', 'arm64')
    assert 'dpkg --add-architecture' not in commands
    assert 'scripts/install_rtpmidid.py --os bookworm --arch arm64' in commands
    assert 'scripts/install_rtpmidid.py --os bookworm --arch armhf' in run_installer_function('install_rtpmidi_server', 'bookworm', 'armhf')


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


@pytest.mark.parametrize('existing_user', [False, True])
def test_identity_preserves_existing_password(existing_user):
    harness = f'''set -euo pipefail
PLV_HOSTNAME=pianoledvisualizer
PLV_USER=plv
execute_command() {{ echo "COMMAND:$1"; }}
getent() {{ return 0; }}
id() {{ return {0 if existing_user else 1}; }}
sudo() {{
  if [ "$1" = chpasswd ]; then
    cat >/dev/null
    echo PASSWORD_CHANGED
  elif [ "$1" = tee ]; then
    cat >/dev/null
  else
    return 1
  fi
}}
systemctl() {{ return 0; }}
{installer_function('configure_pi_identity')}
configure_pi_identity
'''
    result = subprocess.run([BASH, '-c', harness], check=True, text=True, capture_output=True)
    # Account creation leaves it locked until private provisioning after clone.
    assert 'PASSWORD_CHANGED' not in result.stdout
    assert ('useradd' in result.stdout) is not existing_user


def test_network_commands_work_when_icmp_is_blocked():
    harness = f'''set -euo pipefail
ping() {{ echo UNEXPECTED_PING; return 1; }}
sleep() {{ :; }}
download() {{ echo HTTPS_DOWNLOAD; }}
{installer_function('execute_command')}
execute_command download check_internet
'''
    result = subprocess.run([BASH, '-c', harness], check=False, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'HTTPS_DOWNLOAD' in result.stdout
    assert 'UNEXPECTED_PING' not in result.stdout


def test_network_command_retry_preserves_failures_and_stops_on_success():
    harness = f'''set -euo pipefail
ping() {{ return 0; }}
sleep() {{ :; }}
attempts=0
download() {{
  attempts=$((attempts + 1))
  echo "ATTEMPT:$attempts"
  [ "$attempts" -eq 3 ]
}}
{installer_function('execute_command')}
execute_command download check_internet
echo "COMPLETED:$attempts"
'''
    result = subprocess.run([BASH, '-c', harness], check=False, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'COMPLETED:3' in result.stdout


def test_network_command_exhaustion_exits_with_failure():
    harness = f'''set -euo pipefail
ping() {{ return 0; }}
sleep() {{ :; }}
download() {{ echo ATTEMPT; return 23; }}
{installer_function('execute_command')}
execute_command download check_internet
echo UNEXPECTED_SUCCESS
'''
    result = subprocess.run([BASH, '-c', harness], check=False, text=True, capture_output=True)
    assert result.returncode != 0
    assert result.stdout.splitlines().count('ATTEMPT') == 18
    assert 'UNEXPECTED_SUCCESS' not in result.stdout
