"""Installer security boundaries, using temporary files and mocked system tools."""

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import configure_installation_security as security
from scripts import install_rtpmidid as artifacts

ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which('bash') or r'C:\Program Files\Git\bin\bash.exe'


@pytest.fixture
def account_commands(monkeypatch):
    commands = []
    monkeypatch.setattr(security.os, 'chown', Mock(), raising=False)

    def run(command, **kwargs):
        commands.append((command, kwargs))
        output = ''
        if command == ['getent', 'shadow', 'plv']:
            output = 'plv:!:1:0:99999:7:::\n'
        elif command == ['getent', 'passwd', 'plv']:
            output = 'plv:x:1000:1000::/home/plv:/bin/bash\n'
        return SimpleNamespace(stdout=output, returncode=0)

    monkeypatch.setattr(security.subprocess, 'run', run)
    return commands


def test_new_accounts_get_distinct_private_secrets_without_log_disclosure(tmp_path, account_commands, capsys):
    secrets = []
    for index in range(2):
        root = tmp_path / str(index)
        security.initialize_account(root)
        state = root / 'var/lib/plv-bootstrap'
        credentials = state / 'initial-credentials.json'
        secret = json.loads(credentials.read_text())['password']
        secrets.append(secret)
        assert len(secret) >= 32
        if os.name != 'nt':
            assert credentials.stat().st_mode & 0o777 == 0o600
            assert state.stat().st_mode & 0o777 == 0o700
    assert secrets[0] != secrets[1]
    passwords = [(command, kwargs) for command, kwargs in account_commands if command == ['chpasswd']]
    assert len(passwords) == 2
    for secret, (command, kwargs) in zip(secrets, passwords, strict=True):
        assert secret not in str(command)
        assert kwargs['input'] == f'plv:{secret}\n'
    output = capsys.readouterr()
    assert all(secret not in output.out + output.err for secret in secrets)


def test_completed_first_boot_never_resets_password(tmp_path, account_commands):
    security.initialize_account(tmp_path)
    account_commands.clear()
    security.initialize_account(tmp_path)
    assert account_commands == []


def test_key_seed_skips_interactive_userconfig(tmp_path, account_commands):
    boot = tmp_path / 'boot/firmware'
    boot.mkdir(parents=True)
    (boot / 'plv-authorized_keys').write_text('ssh-ed25519 valid-key')
    assert not security.needs_userconfig(tmp_path)
    assert account_commands == []


def test_explicit_os_account_seed_takes_priority_over_ssh_seed(tmp_path, account_commands):
    boot = tmp_path / 'boot/firmware'
    boot.mkdir(parents=True)
    (boot / 'plv-authorized_keys').write_text('ssh-ed25519 valid-key')
    (boot / 'userconf.txt').write_text('administrator:$6$selected-password-hash\n')
    assert security.needs_userconfig(tmp_path)
    assert account_commands == []


@pytest.mark.parametrize('password,expected', [('!', True), ('$6$selected', False)])
def test_userconfig_preserves_configured_accounts_and_keeps_console_path(tmp_path, monkeypatch, password, expected):
    def run(command, **kwargs):
        if command == ['getent', 'passwd']:
            return SimpleNamespace(stdout='plv:x:1000:1000::/home/plv:/bin/bash\n')
        assert command == ['getent', 'shadow', 'plv']
        return SimpleNamespace(stdout=f'plv:{password}:1:0:99999:7:::\n')

    monkeypatch.setattr(security.subprocess, 'run', run)
    assert security.needs_userconfig(tmp_path) is expected


def test_first_boot_recreates_plv_only_if_os_setup_renamed_it(tmp_path, monkeypatch):
    state = tmp_path / 'var/lib/plv-bootstrap'
    state.mkdir(parents=True)
    (state / 'created-account-uid').write_text('1000\n')
    run = Mock(side_effect=[
        SimpleNamespace(returncode=2),
        SimpleNamespace(stdout='selectedadmin:x:1000:1000::/home/selectedadmin:/bin/bash\n'),
        SimpleNamespace(returncode=0), SimpleNamespace(returncode=0),
    ])
    monkeypatch.setattr(security.subprocess, 'run', run)
    security.ensure_plv_account(tmp_path)
    assert run.call_args_list[2].args[0] == ['usermod', '-aG', 'sudo', 'selectedadmin']
    assert run.call_args_list[3].args[0] == ['useradd', '-m', '-s', '/bin/bash', 'plv']
    run.reset_mock(side_effect=True)
    run.return_value = SimpleNamespace(returncode=0)
    security.ensure_plv_account(tmp_path)
    assert run.call_count == 1


def test_deferred_image_records_identity_but_generates_no_password(tmp_path, account_commands):
    security.defer_account(tmp_path)
    state = tmp_path / 'var/lib/plv-bootstrap'
    assert (state / 'created-account-uid').read_text() == '1000\n'
    assert (state / 'account-pending').exists()
    assert not (state / 'initial-credentials.json').exists()
    assert not any(command == ['chpasswd'] for command, _ in account_commands)


def hotspot_project(root):
    project = root / 'home/Piano-LED-Visualizer'
    config = project / 'config'
    config.mkdir(parents=True)
    (config / 'default_settings.xml').write_text('<settings><hotspot_password /></settings>')
    return project


def test_hotspot_defaults_are_unique_private_and_not_logged(tmp_path, account_commands, capsys):
    passwords = []
    for name in ['card-a', 'card-b']:
        root = tmp_path / name
        project = hotspot_project(root)
        security.initialize_hotspot(root)
        password = ET.parse(project / 'config/settings.xml').getroot().findtext('hotspot_password')
        passwords.append(password)
        assert len(password) >= 24
        saved = json.loads((root / 'var/lib/plv-bootstrap/hotspot-credentials.json').read_text())
        assert saved['password'] == password
        if os.name != 'nt':
            assert (project / 'config/settings.xml').stat().st_mode & 0o777 == 0o600
    assert passwords[0] != passwords[1]
    output = capsys.readouterr()
    assert all(password not in output.out + output.err for password in passwords)


@pytest.mark.parametrize('new_account', [True, False])
def test_image_defers_all_per_device_secrets_until_boot(tmp_path, account_commands, monkeypatch, new_account):
    import sys

    monkeypatch.setattr(security, 'STATE', tmp_path / 'bootstrap')
    monkeypatch.setattr(security.os, 'geteuid', lambda: 0, raising=False)
    monkeypatch.setattr(security, 'configure_admin', Mock())
    initialize = Mock()
    monkeypatch.setattr(security, 'initialize_hotspot', initialize)
    defer = Mock()
    monkeypatch.setattr(security, 'defer_account', defer)
    argv = ['security', '--defer-settings']
    if new_account:
        argv.append('--defer-account')
    monkeypatch.setattr(sys, 'argv', argv)
    security.main()
    initialize.assert_not_called()
    assert defer.call_count == int(new_account)
    assert (tmp_path / 'bootstrap/settings-pending').exists()
    assert not list(tmp_path.rglob('*credentials*'))


def test_hotspot_boot_seed_is_known_before_headless_connection(tmp_path, account_commands):
    project = hotspot_project(tmp_path)
    boot = tmp_path / 'boot/firmware'
    boot.mkdir(parents=True)
    seed = boot / 'plv-hotspot-password'
    chosen = 'card-specific-chosen-password'
    seed.write_text(chosen + '\n')
    security.initialize_hotspot(tmp_path)
    assert ET.parse(project / 'config/settings.xml').getroot().findtext('hotspot_password') == chosen
    assert not seed.exists()


def test_existing_hotspot_config_is_preserved_byte_for_byte(tmp_path, account_commands):
    project = hotspot_project(tmp_path)
    settings = project / 'config/settings.xml'
    original = '<settings><hotspot_password>owner-existing-pass</hotspot_password></settings>\n'
    settings.write_text(original)
    security.initialize_hotspot(tmp_path)
    assert settings.read_text() == original
    assert not (tmp_path / 'var/lib/plv-bootstrap').exists()


def test_invalid_hotspot_seed_never_creates_settings(tmp_path, account_commands):
    project = hotspot_project(tmp_path)
    boot = tmp_path / 'boot'
    boot.mkdir()
    (boot / 'plv-hotspot-password').write_text('short')
    with pytest.raises(ValueError, match='Hotspot password'):
        security.initialize_hotspot(tmp_path)
    assert not (project / 'config/settings.xml').exists()


def test_owner_can_choose_hotspot_password_interactively_without_logging(tmp_path, account_commands, monkeypatch, capsys):
    project = hotspot_project(tmp_path)
    settings = project / 'config/settings.xml'
    settings.write_text('<settings><hotspot_password>previous-password</hotspot_password><mode>Fading</mode></settings>')
    chosen = 'my-card-my-own-new-password'
    prompts = iter([chosen, chosen])
    monkeypatch.setattr(security.getpass, 'getpass', lambda prompt: next(prompts))
    security.set_hotspot_password(tmp_path)
    result = ET.parse(settings).getroot()
    assert result.findtext('hotspot_password') == chosen
    assert result.findtext('mode') == 'Fading'
    assert chosen not in capsys.readouterr().out


def test_missing_hotspot_password_never_activates_public_fallback(monkeypatch):
    from lib.platform import PlatformRasp

    run = Mock()
    monkeypatch.setattr('lib.platform.subprocess.run', run)
    assert PlatformRasp._get_hotspot_password() is None
    assert not PlatformRasp.enable_hotspot()
    run.assert_not_called()
    assert PlatformRasp._get_hotspot_password({'hotspot_password': 'visualizer'}) == 'visualizer'


def test_hotspot_configuration_failure_cannot_log_psk(monkeypatch, caplog, capsys):
    from lib.platform import PlatformRasp

    secret = 'do-not-log-this-owner-passphrase'

    def run(command, **kwargs):
        if 'modify' in command:
            assert kwargs['capture_output']
            raise subprocess.CalledProcessError(2, command, stderr=f'bad PSK {secret}')
        return subprocess.CompletedProcess(command, 0, 'Hotspot', '')

    monkeypatch.setattr('lib.platform.subprocess.run', run)
    assert not PlatformRasp.create_hotspot_profile(secret)
    output = capsys.readouterr()
    assert secret not in caplog.text + output.out + output.err


def test_imager_password_is_preserved(tmp_path, account_commands, monkeypatch):
    original = security.subprocess.run

    def configured(command, **kwargs):
        if command == ['getent', 'shadow', 'plv']:
            return SimpleNamespace(stdout='plv:$6$already-chosen:1:0:99999:7:::\n')
        return original(command, **kwargs)

    monkeypatch.setattr(security.subprocess, 'run', configured)
    security.initialize_account(tmp_path)
    assert not any(command == ['chpasswd'] for command, _ in account_commands)
    assert not (tmp_path / 'var/lib/plv-bootstrap/initial-credentials.json').exists()


def test_imager_key_only_account_remains_password_locked(tmp_path, account_commands):
    directory = tmp_path / 'home/plv/.ssh'
    directory.mkdir(parents=True)
    key = directory / 'authorized_keys'
    key.write_text('ssh-ed25519 imager-key existing-admin\n')
    security.initialize_account(tmp_path)
    assert not any(command == ['chpasswd'] for command, _ in account_commands)
    assert key.read_text() == 'ssh-ed25519 imager-key existing-admin\n'
    assert not (tmp_path / 'var/lib/plv-bootstrap/initial-credentials.json').exists()


def test_seed_key_is_validated_and_preserves_existing_authorized_keys(tmp_path, account_commands):
    boot = tmp_path / 'boot/firmware'
    boot.mkdir(parents=True)
    seed = boot / 'plv-authorized_keys'
    seed.write_text('ssh-ed25519 seed-key new-admin\n')
    directory = tmp_path / 'home/plv/.ssh'
    directory.mkdir(parents=True)
    key = directory / 'authorized_keys'
    key.write_text('ssh-ed25519 existing-key existing-admin\n')
    security.initialize_account(tmp_path)
    assert key.read_text().splitlines() == [
        'ssh-ed25519 existing-key existing-admin', 'ssh-ed25519 seed-key new-admin']
    assert not seed.exists()
    assert account_commands[0][0] == ['ssh-keygen', '-l', '-f', str(seed)]


def test_invalid_seed_never_changes_password(tmp_path, account_commands, monkeypatch):
    boot = tmp_path / 'boot'
    boot.mkdir()
    (boot / 'plv-authorized_keys').write_text('not a public key')

    def invalid(command, **kwargs):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(security.subprocess, 'run', invalid)
    with pytest.raises(subprocess.CalledProcessError):
        security.initialize_account(tmp_path)
    assert not (tmp_path / 'var/lib/plv-bootstrap/initial-credentials.json').exists()
    assert account_commands == []


def test_admin_rules_replace_only_legacy_plv_grant(tmp_path, account_commands):
    project = tmp_path / 'project'
    (project / 'scripts').mkdir(parents=True)
    shutil.copyfile(ROOT / 'scripts/plv-admin.sh', project / 'scripts/plv-admin.sh')
    sudoers = tmp_path / 'etc/sudoers.d'
    sudoers.mkdir(parents=True)
    legacy = sudoers / '010_pi-nopasswd'
    legacy.write_text('plv ALL=(ALL) NOPASSWD: ALL\nadmin ALL=(ALL) ALL\n')
    security.configure_admin(tmp_path, project)
    assert legacy.read_text() == 'admin ALL=(ALL) ALL\n'
    rule = (sudoers / '020-plv-admin').read_text()
    assert 'NOPASSWD: /usr/local/sbin/plv-admin' in rule
    assert 'NOPASSWD: ALL' not in rule
    assert '!setenv' in rule
    assert any(command[:2] == ['visudo', '-cf'] for command, _ in account_commands)


def test_rejected_sudoers_keeps_previous_access_and_installs_no_rule(tmp_path, account_commands, monkeypatch):
    project = tmp_path / 'project'
    (project / 'scripts').mkdir(parents=True)
    shutil.copyfile(ROOT / 'scripts/plv-admin.sh', project / 'scripts/plv-admin.sh')
    sudoers = tmp_path / 'etc/sudoers.d'
    sudoers.mkdir(parents=True)
    legacy = sudoers / '010_pi-nopasswd'
    original = 'plv ALL=(ALL) NOPASSWD: ALL\n'
    legacy.write_text(original)

    def rejected(command, **kwargs):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(security.subprocess, 'run', rejected)
    with pytest.raises(subprocess.CalledProcessError):
        security.configure_admin(tmp_path, project)
    assert legacy.read_text() == original
    assert not (sudoers / '020-plv-admin').exists()
    assert not (sudoers / '.plv-admin.tmp').exists()


@pytest.mark.parametrize('action,expected', [
    ('restart', 'systemctl><restart><visualizer.service'),
    ('restart-midi', 'systemctl><restart><rtpmidid.service'),
    ('update', '.venv/bin/python><-I>'),
    ('logs', 'journalctl><--no-pager>'),
    ('protection-status', 'status_safe_poweroff.sh'),
])
def test_admin_helper_dispatches_only_fixed_commands(action, expected):
    helper = (ROOT / 'scripts/plv-admin.sh').as_posix()
    harness = '''exec() { printf '<%s>' "$@"; printf '\n'; }
export PYTHONPATH=/untrusted PLV_DIR=/untrusted
source "$1" "$2"
test -z "${PYTHONPATH:-}${PLV_DIR:-}"
'''
    result = subprocess.run([BASH, '-c', harness, 'test', helper, action], check=True, capture_output=True, text=True)
    assert expected in result.stdout
    assert '/untrusted' not in result.stdout


@pytest.mark.parametrize('args', [['/bin/bash'], ['update; /bin/sh'], ['update', '--remote-url', 'https://attacker.invalid'], []])
def test_admin_helper_rejects_arbitrary_commands_and_extra_arguments(args):
    result = subprocess.run([BASH, str(ROOT / 'scripts/plv-admin.sh'), *args], check=False, capture_output=True, text=True)
    assert result.returncode == 2


class Response(io.BytesIO):
    def geturl(self):
        return 'https://official.example/artifact'


@pytest.mark.parametrize('platform', list(artifacts.ARTIFACTS))
def test_download_mismatch_never_installs_or_builds(platform, monkeypatch):
    monkeypatch.setattr(artifacts, 'urlopen', lambda *args, **kwargs: Response(b'modified executable'))
    run = Mock()
    monkeypatch.setattr(artifacts, 'run', run)
    with pytest.raises(ValueError, match='SHA256 mismatch'):
        artifacts.install(*platform)
    run.assert_not_called()


def test_pinned_package_is_verified_before_install(monkeypatch):
    payload = b'reviewed package'
    monkeypatch.setitem(artifacts.ARTIFACTS, ('bookworm', 'armhf'),
                        ('https://official.example/artifact', hashlib.sha256(payload).hexdigest()))
    monkeypatch.setattr(artifacts, 'urlopen', lambda *args, **kwargs: Response(payload))
    commands = []

    def run(*command):
        assert command[:3] == ('apt-get', 'install', '-y')
        assert command[-1].read_bytes() == payload
        commands.append(command)

    monkeypatch.setattr(artifacts, 'run', run)
    artifacts.install('bookworm', 'armhf')
    assert len(commands) == 1


def test_download_offline_never_installs(monkeypatch):
    def offline(*args, **kwargs):
        raise OSError('offline')

    monkeypatch.setattr(artifacts, 'urlopen', offline)
    run = Mock()
    monkeypatch.setattr(artifacts, 'run', run)
    with pytest.raises(OSError, match='offline'):
        artifacts.install('bookworm', 'armhf')
    run.assert_not_called()


def test_insecure_redirect_never_installs(monkeypatch):
    class InsecureResponse(Response):
        def geturl(self):
            return 'http://insecure.example/artifact'

    monkeypatch.setattr(artifacts, 'urlopen', lambda *args, **kwargs: InsecureResponse(b'content'))
    run = Mock()
    monkeypatch.setattr(artifacts, 'run', run)
    with pytest.raises(ValueError, match='outside HTTPS'):
        artifacts.install('bookworm', 'armhf')
    run.assert_not_called()


def test_pinned_source_archive_is_verified_before_build(tmp_path, monkeypatch):
    archive_bytes = io.BytesIO()
    with tarfile.open(fileobj=archive_bytes, mode='w:gz') as archive:
        for name, content in [('default.ini', b'[general]\n'), ('debian/rtpmidid.service', b'[Service]\n')]:
            member = tarfile.TarInfo(f'rtpmidid-{artifacts.SOURCE_COMMIT}/{name}')
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
    payload = archive_bytes.getvalue()
    monkeypatch.setitem(artifacts.ARTIFACTS, ('trixie', 'armhf'),
                        ('https://official.example/artifact', hashlib.sha256(payload).hexdigest()))
    monkeypatch.setattr(artifacts, 'urlopen', lambda *args, **kwargs: Response(payload))
    monkeypatch.setattr(artifacts, 'SYSTEM_ROOT', tmp_path)
    (tmp_path / 'lib/systemd/system').mkdir(parents=True)
    commands = []
    monkeypatch.setattr(artifacts, 'run', lambda *command: commands.append(command))
    monkeypatch.setattr(artifacts.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=0))
    artifacts.install('trixie', 'armhf')
    assert commands[0][0] == 'cmake'
    assert commands[1][:2] == ('cmake', '--build')
    assert (tmp_path / 'etc/rtpmidid/default.ini').read_bytes() == b'[general]\n'
    assert (tmp_path / 'lib/systemd/system/rtpmidid.service').read_bytes() == b'[Service]\n'


def test_image_contains_no_generated_credentials_and_installs_verified_artifacts():
    script = (ROOT / 'scripts/image-install.sh').read_text()
    assert '--defer-account' in script
    assert 'plv:visualizer' not in script
    assert 'NOPASSWD: ALL' not in script
    assert 'userdel' not in script
    assert 'scripts/install_rtpmidid.py' in script
    assert not re.search(r'^\s*curl\s', script, re.MULTILINE)


def test_new_install_makes_account_privileges_effective_by_protecting_runtime_code():
    secure = (ROOT / 'scripts/secure_installation.sh').read_text()
    assert '-exec chown root:root' in secure
    assert '-exec chmod go-w' in secure
    installer = (ROOT / 'autoinstall.sh').read_text()
    assert 'scripts/secure_installation.sh' in installer
    assert 'PLV_PASSWORD=' not in installer
    assert 'local user_groups="sudo"' not in installer


def test_image_build_checks_pinned_bytes_before_execution():
    workflow = (ROOT / '.github/workflows/main.yml').read_text()
    assert 'BASE_SHA256: 6332f7a232acd7d05f9499273e9a28783bbf1d23e3b1053784167793159044dd' in workflow
    check = "echo '71026f0c02ac099e588a3eb8f70760c1b680aa8ea3acde61a0141fbaeb68c777  pishrink.sh' | sha256sum --check --strict"
    assert workflow.index(check) < workflow.index('sudo bash pishrink.sh')


@pytest.mark.parametrize('name,kind', [('../escape', tarfile.REGTYPE), ('link', tarfile.SYMTYPE)])
def test_source_extraction_rejects_unsafe_members(tmp_path, name, kind):
    archive_path = tmp_path / 'bad.tar.gz'
    with tarfile.open(archive_path, 'w:gz') as archive:
        member = tarfile.TarInfo(name)
        member.type = kind
        member.linkname = '/outside'
        archive.addfile(member)
    with pytest.raises(ValueError, match='Unsafe member'):
        artifacts.extract_source(archive_path, tmp_path / 'source')
    assert not (tmp_path / 'escape').exists()
