#!/usr/bin/env python3
"""Provision private first-login credentials and a restricted PLV admin helper."""

import argparse
import getpass
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

APP = Path('/home/Piano-LED-Visualizer')
STATE = Path('/var/lib/plv-bootstrap')
LEGACY_GRANT = re.compile(r'^\s*plv\s+ALL\s*=\s*\(ALL(?::ALL)?\)\s+NOPASSWD:\s*ALL\s*(?:#.*)?$')


def validate_hotspot_password(password):
    if (not isinstance(password, str) or any(char in password for char in '\r\n\0')
            or not (8 <= len(password.encode('utf-8')) <= 63
                    or (len(password) == 64 and all(char in '0123456789abcdefABCDEF' for char in password)))):
        raise ValueError('Hotspot password must be 8-63 bytes, or a 64-digit hexadecimal PSK')
    return password


def save_hotspot_credentials(state, password):
    private_directory(state)
    destination = state / 'hotspot-credentials.json'
    if destination.is_symlink():
        raise ValueError('Hotspot credential file must not be a symlink')
    destination.unlink(missing_ok=True)
    write_private(destination, json.dumps({'ssid': 'PianoLEDVisualizer', 'password': password}) + '\n')


def initialize_hotspot(root=Path('/'), project=None):
    project = project or root / APP.relative_to('/')
    settings = project / 'config/settings.xml'
    if settings.exists():
        return  # Existing passwords, including intentionally chosen ones, stay unchanged.
    state = root / STATE.relative_to('/')
    seed = root / 'boot/firmware/plv-hotspot-password'
    if not seed.exists():
        seed = root / 'boot/plv-hotspot-password'
    stored = state / 'hotspot-credentials.json'
    if seed.is_file():
        password = validate_hotspot_password(seed.read_text(encoding='utf-8').rstrip('\r\n'))
    elif stored.is_file() and not stored.is_symlink():
        password = validate_hotspot_password(json.loads(stored.read_text(encoding='utf-8'))['password'])
    else:
        password = secrets.token_urlsafe(24)
    tree = ET.parse(project / 'config/default_settings.xml')
    field = tree.getroot().find('hotspot_password')
    if field is None:
        field = ET.SubElement(tree.getroot(), 'hotspot_password')
    field.text = password
    save_hotspot_credentials(state, password)
    write_private(settings, ET.tostring(tree.getroot(), encoding='unicode') + '\n')
    if seed.is_file():
        seed.unlink()


def set_hotspot_password(root=Path('/')):
    password = validate_hotspot_password(getpass.getpass('Choose hotspot password: '))
    if getpass.getpass('Confirm hotspot password: ') != password:
        raise ValueError('Hotspot password confirmation did not match')
    settings = root / APP.relative_to('/') / 'config/settings.xml'
    tree = ET.parse(settings)
    field = tree.getroot().find('hotspot_password')
    if field is None:
        field = ET.SubElement(tree.getroot(), 'hotspot_password')
    field.text = password
    descriptor, temporary = tempfile.mkstemp(prefix='.settings-', dir=settings.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
            output.write(ET.tostring(tree.getroot(), encoding='unicode') + '\n')
        os.chown(temporary, 0, 0)
        temporary.replace(settings)
    finally:
        temporary.unlink(missing_ok=True)
    save_hotspot_credentials(root / STATE.relative_to('/'), password)


def needs_userconfig(root=Path('/')):
    """Keep explicit OS setup, but never block seeded SSH behind a TTY dialog."""
    boot_directories = [root / 'boot/firmware', root / 'boot']
    if any((boot / name).is_file() for boot in boot_directories for name in ('userconf', 'userconf.txt')):
        return True
    if any((boot / 'plv-authorized_keys').is_file() for boot in boot_directories):
        return False
    accounts = subprocess.run(['getent', 'passwd'], check=True, capture_output=True, text=True).stdout
    for line in accounts.splitlines():
        fields = line.split(':')
        if len(fields) != 7 or not 1000 <= int(fields[2]) < 65534:
            continue
        shadow = subprocess.run(['getent', 'shadow', fields[0]], check=True,
                                capture_output=True, text=True).stdout.split(':')
        if len(shadow) > 1 and shadow[1] and not shadow[1].startswith(('!', '*')):
            return False
        home = root / Path(fields[5]).relative_to('/')
        key = home / '.ssh/authorized_keys'
        if key.is_file() and key.stat().st_size:
            return False
    return True


def defer_account(root=Path('/')):
    state = root / STATE.relative_to('/')
    private_directory(state)
    account = subprocess.run(['getent', 'passwd', 'plv'], check=True, capture_output=True, text=True).stdout.split(':')
    uid = int(account[2])
    if uid < 1000 or uid >= 65534:
        raise ValueError('Unexpected initial PLV account UID')
    identity = state / 'created-account-uid'
    if not identity.exists():
        write_private(identity, f'{uid}\n')
    pending = state / 'account-pending'
    if not pending.exists():
        write_private(pending, 'Generate per-device credentials on first boot.\n')


def ensure_plv_account(root=Path('/')):
    """OS userconf may have renamed the image's first account to its admin."""
    account = subprocess.run(['getent', 'passwd', 'plv'], check=False, capture_output=True)
    if account.returncode:
        identity = root / STATE.relative_to('/') / 'created-account-uid'
        uid = int(identity.read_text(encoding='utf-8').strip())
        renamed = subprocess.run(['getent', 'passwd', str(uid)], check=True,
                                 capture_output=True, text=True).stdout.split(':')
        if len(renamed) != 7 or renamed[0] in {'root', 'plv'} or int(renamed[2]) != uid or not 1000 <= uid < 65534:
            raise ValueError('Cannot identify the administrator selected during OS setup')
        # userconf renames the initial user without adding groups. Give only
        # that explicitly configured administrator password-based sudo, then
        # create a separate PLV account which never joins the sudo group.
        subprocess.run(['usermod', '-aG', 'sudo', renamed[0]], check=True, capture_output=True)
        subprocess.run(['useradd', '-m', '-s', '/bin/bash', 'plv'], check=True, capture_output=True)


def private_directory(path):
    if path.is_symlink():
        raise ValueError('Bootstrap state must not be a symlink')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    os.chown(path, 0, 0)


def write_private(path, text):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
        output.write(text)
    os.chown(path, 0, 0)


def initialize_account(root=Path('/')):
    """Called only for accounts created by this installer, never on upgrades."""
    state = root / STATE.relative_to('/')
    private_directory(state)
    complete = state / 'account-provisioned'
    if complete.exists():
        (state / 'account-pending').unlink(missing_ok=True)
        return
    seed = root / 'boot/firmware/plv-authorized_keys'
    if not seed.exists():
        seed = root / 'boot/plv-authorized_keys'
    if seed.exists():
        # Validate the administrator-supplied public key before changing access.
        subprocess.run(['ssh-keygen', '-l', '-f', str(seed)], check=True, capture_output=True)
    shadow = subprocess.run(['getent', 'shadow', 'plv'], check=True, capture_output=True, text=True).stdout.split(':')
    if len(shadow) < 2:
        raise ValueError('Cannot inspect the PLV account credential state')
    account = subprocess.run(['getent', 'passwd', 'plv'], check=True, capture_output=True, text=True).stdout.split(':')
    if len(account) != 7:
        raise ValueError('Cannot inspect the PLV account home directory')
    home = root / Path(account[5]).relative_to('/')
    existing_key = home / '.ssh/authorized_keys'
    # Imager/userconfig may have provisioned this account before our first boot.
    # A configured (including intentionally locked) password must be preserved.
    configured = (shadow[1] not in {'', '!', '!!', '*'}
                  or (existing_key.is_file() and existing_key.stat().st_size > 0))
    credentials = state / 'initial-credentials.json'
    if credentials.is_symlink():
        raise ValueError('Bootstrap credentials must not be a symlink')
    if not configured and not credentials.exists():
        write_private(credentials, json.dumps({'user': 'plv', 'password': secrets.token_urlsafe(32)}) + '\n')
    if not configured:
        credentials.chmod(0o600)
        os.chown(credentials, 0, 0)
        password = json.loads(credentials.read_text(encoding='utf-8'))['password']
        if not isinstance(password, str) or not password or any(char in password for char in '\r\n:'):
            raise ValueError('Invalid stored bootstrap password')
        # Password is passed through stdin; neither argv nor stdout contains it.
        subprocess.run(['chpasswd'], input=f'plv:{password}\n', text=True, check=True, capture_output=True)
    if seed.exists():
        uid, gid = int(account[2]), int(account[3])
        directory = home / '.ssh'
        if directory.is_symlink():
            raise ValueError('SSH directory must not be a symlink')
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory.chmod(0o700)
        key = directory / 'authorized_keys'
        if key.is_symlink():
            raise ValueError('SSH key file must not be a symlink')
        # This path is only reached for a newly created PLV account. Preserve
        # any keys already supplied by Imager instead of replacing them.
        previous = key.read_text(encoding='utf-8') if key.exists() else ''
        with key.open('w', encoding='utf-8') as output:
            output.write(previous.rstrip('\n') + '\n' + seed.read_text(encoding='utf-8').rstrip('\n') + '\n')
        key.chmod(0o600)
        os.chown(directory, uid, gid)
        os.chown(key, uid, gid)
        seed.unlink()
    write_private(complete, 'Account provisioned; do not reset its password.\n')
    (state / 'account-pending').unlink(missing_ok=True)
    if not configured:
        print('Initial PLV credentials are stored locally in /var/lib/plv-bootstrap/initial-credentials.json (root only).')


def configure_admin(root=Path('/'), project=None):
    project = project or root / APP.relative_to('/')
    helper = root / 'usr/local/sbin/plv-admin'
    helper.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(project / 'scripts/plv-admin.sh', helper)
    os.chown(helper, 0, 0)
    helper.chmod(0o755)
    sudoers = root / 'etc/sudoers.d'
    sudoers.mkdir(parents=True, exist_ok=True)
    temporary = sudoers / '.plv-admin.tmp'
    temporary.write_text('Defaults!/usr/local/sbin/plv-admin !setenv\n'
                         'plv ALL=(root) NOPASSWD: /usr/local/sbin/plv-admin\n', encoding='utf-8')
    temporary.chmod(0o440)
    os.chown(temporary, 0, 0)
    try:
        subprocess.run(['visudo', '-cf', str(temporary)], check=True, capture_output=True)
        temporary.replace(sudoers / '020-plv-admin')
    finally:
        if temporary.exists():
            temporary.chmod(0o600)
            temporary.unlink()
    legacy = sudoers / '010_pi-nopasswd'
    if legacy.exists():
        lines = legacy.read_text(encoding='utf-8').splitlines()
        retained = [line for line in lines if not LEGACY_GRANT.fullmatch(line)]
        if retained != lines:
            legacy.write_text('\n'.join(retained) + '\n', encoding='utf-8')
            legacy.chmod(0o440)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--initialize-account', action='store_true')
    parser.add_argument('--defer-account', action='store_true')
    parser.add_argument('--defer-settings', action='store_true')
    parser.add_argument('--first-boot', action='store_true')
    parser.add_argument('--needs-userconfig', action='store_true')
    parser.add_argument('--set-hotspot-password', action='store_true')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise PermissionError('Run installation security configuration as root')
    if args.needs_userconfig:
        raise SystemExit(0 if needs_userconfig() else 1)
    if args.set_hotspot_password:
        set_hotspot_password()
        return
    if args.first_boot:
        pending = STATE / 'account-pending'
        if pending.exists():
            ensure_plv_account()
        initialize_hotspot()
        if pending.exists():
            initialize_account()
        (STATE / 'settings-pending').unlink(missing_ok=True)
        return
    configure_admin(project=Path(__file__).resolve().parents[1])
    if args.defer_account or args.defer_settings:
        private_directory(STATE)
        settings_pending = STATE / 'settings-pending'
        if not settings_pending.exists():
            write_private(settings_pending, 'Generate per-device settings on first boot.\n')
        if args.defer_account:
            defer_account()
    else:
        initialize_hotspot(project=Path(__file__).resolve().parents[1])
        if args.initialize_account:
            initialize_account()


if __name__ == '__main__':
    main()
