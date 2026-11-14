#!/usr/bin/env python3
"""Install reviewed rtpmidid artifacts, checking pinned bytes before use."""

import argparse
import hashlib
import hmac
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from urllib.request import urlopen

# v26.01 package digest is published by GitHub's upstream release API.
# v24.12 predates those digests: these review-time pins were obtained from the
# official release asset IDs 213481992/213524010. They are not publisher signatures.
# See Docs/manual_installation.md for provenance and the pin-update procedure.
BASE = 'https://github.com/davidmoreno/rtpmidid/releases/download'
SOURCE_COMMIT = 'c3a289cda674a7a3ec53c137d05caf5c42aa3f21'
ARTIFACTS = {
    ('bookworm', 'armhf'): (
        f'{BASE}/v24.12/rtpmidid_24.12.2_armhf.deb',
        'fe3b1d52fd841b0025a8007a0f27d44ad8675093b1c0ca003ccbb3fd77150f4a',
    ),
    ('bookworm', 'arm64'): (
        f'{BASE}/v24.12/rtpmidid_24.12.2_arm64.deb',
        'a6de736eadaad16f6ebe58c26465f37dc694e25b216502429e4299af146aebb3',
    ),
    ('trixie', 'arm64'): (
        f'{BASE}/v26.01/rtpmidid-debian-trixie-arm64-26.01.deb',
        'c746c3a7da1bb73efcd8fa24ce996fa558af6d40aec03e554057e6932ceab5c6',
    ),
    ('trixie', 'armhf'): (
        f'https://codeload.github.com/davidmoreno/rtpmidid/tar.gz/{SOURCE_COMMIT}',
        '909e8f4f99024930e32e0e1f7ade8f946e981ef2fe0f1f54369a9f0d6b7526fe',
    ),
}
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
SYSTEM_ROOT = Path('/')


def download_verified(url, expected_sha256, destination):
    """An unavailable endpoint or changed artifact is a hard installation error."""
    digest = hashlib.sha256()
    size = 0
    with urlopen(url, timeout=30) as response, destination.open('xb') as output:
        if not response.geturl().startswith('https://'):
            raise ValueError('Executable download was redirected outside HTTPS')
        while chunk := response.read(64 * 1024):
            size += len(chunk)
            if size > MAX_ARTIFACT_BYTES:
                raise ValueError('Executable download exceeds size limit')
            digest.update(chunk)
            output.write(chunk)
    if not hmac.compare_digest(digest.hexdigest(), expected_sha256):
        destination.unlink()
        raise ValueError('rtpmidid SHA256 mismatch; nothing was installed')


def extract_source(archive_path, destination):
    with tarfile.open(archive_path, 'r:gz') as archive:
        for member in archive.getmembers():
            target = (destination / member.name).resolve()
            if not target.is_relative_to(destination.resolve()) or not (member.isfile() or member.isdir()):
                raise ValueError('Unsafe member in rtpmidid source archive')
        # Only ordinary files/directories are accepted, including on older 3.11.
        if hasattr(tarfile, 'data_filter'):
            archive.extractall(destination, filter='data')
        else:
            archive.extractall(destination)
    return destination / f'rtpmidid-{SOURCE_COMMIT}'


def run(*command):
    subprocess.run([str(arg) for arg in command], check=True)


def install(os_name, arch):
    try:
        url, digest = ARTIFACTS[(os_name, arch)]
    except KeyError as error:
        raise ValueError('Unsupported rtpmidid OS/architecture') from error
    with tempfile.TemporaryDirectory(prefix='plv-rtpmidid-') as temporary:
        stage = Path(temporary)
        source_build = (os_name, arch) == ('trixie', 'armhf')
        artifact = stage / ('source.tar.gz' if source_build else 'rtpmidid.deb')
        download_verified(url, digest, artifact)
        if not source_build:
            run('apt-get', 'install', '-y', artifact)
            return
        source = extract_source(artifact, stage)
        build = source / 'build'
        run('cmake', '-S', source, '-B', build, '-DCMAKE_BUILD_TYPE=Release',
            '-DENABLE_TESTS=OFF', '-DENABLE_PCH=OFF', '-DUSE_FMT=ON', '-DCPP_VERSION=17', '-GNinja')
        run('cmake', '--build', build)
        run('install', '-m', '755', build / 'src/rtpmidid', SYSTEM_ROOT / 'usr/bin/rtpmidid')
        config = SYSTEM_ROOT / 'etc/rtpmidid'
        config.mkdir(parents=True, exist_ok=True)
        if not (config / 'default.ini').exists():
            shutil.copyfile(source / 'default.ini', config / 'default.ini')
        shutil.copyfile(source / 'debian/rtpmidid.service', SYSTEM_ROOT / 'lib/systemd/system/rtpmidid.service')
        account = subprocess.run(['id', '-u', 'rtpmidid'], check=False, capture_output=True)
        if account.returncode:
            run('useradd', '-r', '-s', '/usr/sbin/nologin', '-G', 'audio', 'rtpmidid')
        run('systemctl', 'daemon-reload')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--os', required=True, choices=('bookworm', 'trixie'))
    parser.add_argument('--arch', required=True, choices=('armhf', 'arm64'))
    args = parser.parse_args()
    install(args.os, args.arch)


if __name__ == '__main__':
    main()
