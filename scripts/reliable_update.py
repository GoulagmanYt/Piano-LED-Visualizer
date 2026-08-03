#!/usr/bin/env python3
"""Transactional updater for Piano LED Visualizer.

The updater runs outside visualizer.service so it can safely restart the
application, verify the HTTP health endpoint and roll back without depending
on the newly installed code.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from typing import Iterable
from urllib.error import URLError
from urllib.request import urlopen

try:
    import fcntl
except ImportError:  # pragma: no cover - the updater itself only runs on Linux
    fcntl = None


DEFAULT_REMOTE = "https://github.com/GoulagmanYt/Piano-LED-Visualizer.git"
DEFAULT_BRANCH = "master"
DEFAULT_STATE_DIR = Path("/var/lib/piano-led-visualizer")
DEFAULT_BACKUP_DIR = Path("/var/backups/piano-led-visualizer")
TERMINAL_STATES = {"success", "no_update", "rolled_back", "failed"}
PERSISTENT_PATHS = (
    "Songs",
    "config/settings.xml",
    "config/sequences.xml",
    "config/presets",
    "config/practice-backup",
    "config/wpa_disable_ap.conf",
    "data",
    "profiles.db",
    "profiles.db-shm",
    "profiles.db-wal",
    "score_log.txt",
    "score_log.txt.1",
    "score_log.txt.2",
    "score_log.txt.3",
)


class UpdateError(RuntimeError):
    pass


def run(command: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )
    if check and result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise UpdateError(f"Command failed ({result.returncode}): {' '.join(command)}: {detail}")
    return result


def atomic_json_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


class StatusWriter:
    def __init__(self, path: Path):
        self.path = path
        self.payload: dict = {
            "state": "starting",
            "message": "Initialisation de la mise à jour",
            "started_at": int(time.time()),
            "updated_at": int(time.time()),
        }
        atomic_json_write(self.path, self.payload)

    def update(self, state: str, message: str, **extra) -> None:
        self.payload.update(extra)
        self.payload.update(state=state, message=message, updated_at=int(time.time()))
        atomic_json_write(self.path, self.payload)


def git_command(project_dir: Path, *arguments: str) -> list[str]:
    resolved = project_dir.resolve()
    return ["git", "-c", f"safe.directory={resolved}", "-C", str(resolved), *arguments]


def git_output(project_dir: Path, *arguments: str) -> str:
    return run(git_command(project_dir, *arguments)).stdout.strip()


def changed_source_files(project_dir: Path) -> list[str]:
    changed = set()
    for args in (("diff", "--name-only"), ("diff", "--cached", "--name-only")):
        output = git_output(project_dir, *args)
        changed.update(line.strip() for line in output.splitlines() if line.strip())

    persistent = tuple(path.rstrip("/") for path in PERSISTENT_PATHS)
    return sorted(
        path for path in changed
        if not any(path == item or path.startswith(item + "/") for item in persistent)
    )


def create_backup(project_dir: Path, backup_dir: Path, revision: str) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    destination = backup_dir / f"plv-{stamp}-{revision[:8]}.tar.gz"
    with tarfile.open(destination, "w:gz") as archive:
        for relative in PERSISTENT_PATHS:
            source = project_dir / relative
            if source.exists():
                archive.add(source, arcname=relative, recursive=True)
    return destination


def ensure_backup_space(project_dir: Path, backup_dir: Path) -> None:
    backup_dir.mkdir(parents=True, exist_ok=True)
    content_size = 0
    for relative in PERSISTENT_PATHS:
        source = project_dir / relative
        if source.is_file():
            content_size += source.stat().st_size
        elif source.is_dir():
            content_size += sum(
                path.stat().st_size for path in source.rglob("*")
                if path.is_file() and not path.is_symlink()
            )
    required = int(content_size * 1.1) + 16 * 1024 * 1024
    free = shutil.disk_usage(backup_dir).free
    if free < required:
        raise UpdateError(
            f"Not enough space for a safe backup: {required} bytes required, {free} bytes available"
        )


def restore_backup(project_dir: Path, backup_path: Path) -> None:
    project_root = project_dir.resolve()
    with tarfile.open(backup_path, "r:gz") as archive:
        for member in archive.getmembers():
            destination = (project_root / member.name).resolve()
            if destination != project_root and project_root not in destination.parents:
                raise UpdateError(f"Unsafe backup member: {member.name}")
        archive.extractall(project_root)


def prune_backups(backup_dir: Path, keep: int = 5) -> None:
    backups = sorted(backup_dir.glob("plv-*.tar.gz"), key=lambda path: path.stat().st_mtime, reverse=True)
    for obsolete in backups[keep:]:
        obsolete.unlink(missing_ok=True)


def install_requirements(requirements: Path) -> None:
    if not requirements.exists():
        raise UpdateError(f"Missing requirements file: {requirements}")
    base_command = [sys.executable, "-m", "pip", "install", "-r", str(requirements)]
    result = run(base_command + ["--break-system-packages"], check=False)
    if result.returncode and "no such option: --break-system-packages" in result.stderr:
        result = run(base_command, check=False)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise UpdateError(f"Dependency installation failed: {detail}")


def validate_release(release_dir: Path) -> None:
    required = (
        release_dir / "visualizer.py",
        release_dir / "requirements.txt",
        release_dir / "lib" / "platform.py",
        release_dir / "webinterface" / "views_api.py",
    )
    missing = [str(path.relative_to(release_dir)) for path in required if not path.is_file()]
    if missing:
        raise UpdateError(f"Release is incomplete: {', '.join(missing)}")
    run(
        [sys.executable, "-m", "compileall", "-q", "-f", "visualizer.py", "lib", "webinterface"],
        cwd=release_dir,
    )


def configured_web_port(project_dir: Path) -> int:
    import xml.etree.ElementTree as ET

    for settings in (project_dir / "config/settings.xml", project_dir / "config/default_settings.xml"):
        try:
            value = ET.parse(settings).getroot().findtext("web_listen_port")
            if value:
                return int(value)
        except (OSError, ValueError, ET.ParseError):
            continue
    return 80


def wait_for_health(project_dir: Path, timeout: float = 45.0) -> bool:
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{configured_web_port(project_dir)}/api/health"
    while time.monotonic() < deadline:
        service = run(["systemctl", "is-active", "--quiet", "visualizer.service"], check=False)
        if service.returncode == 0:
            try:
                with urlopen(url, timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if response.status == 200 and payload.get("success") is True:
                    return True
            except (OSError, URLError, ValueError, json.JSONDecodeError):
                pass
        time.sleep(1)
    return False


def restart_visualizer() -> None:
    run(["systemctl", "restart", "visualizer.service"])


def prepare_staging(project_dir: Path, target_revision: str) -> Path:
    staging_root = Path(tempfile.mkdtemp(prefix="plv-update-"))
    staging = staging_root / "release"
    try:
        run(git_command(project_dir, "worktree", "add", "--detach", str(staging), target_revision))
        validate_release(staging)
        return staging
    except Exception:
        shutil.rmtree(staging_root, ignore_errors=True)
        raise


def remove_staging(project_dir: Path, staging: Path | None) -> None:
    if staging is None:
        return
    run(git_command(project_dir, "worktree", "remove", "--force", str(staging)), check=False)
    shutil.rmtree(staging.parent, ignore_errors=True)
    run(git_command(project_dir, "worktree", "prune"), check=False)


def activate_revision(project_dir: Path, revision: str, backup_path: Path) -> None:
    run(git_command(project_dir, "reset", "--hard", revision))
    restore_backup(project_dir, backup_path)


def perform_update(
    project_dir: Path,
    status: StatusWriter,
    backup_dir: Path,
    remote_url: str,
    branch: str,
) -> int:
    staging: Path | None = None
    backup_path: Path | None = None
    previous_revision = git_output(project_dir, "rev-parse", "HEAD")
    status.update("fetching", "Recherche d'une nouvelle version", previous_revision=previous_revision)

    dirty_sources = changed_source_files(project_dir)
    if dirty_sources:
        raise UpdateError(
            "Local source changes must be committed or removed first: " + ", ".join(dirty_sources[:10])
        )

    run(git_command(project_dir, "remote", "set-url", "origin", remote_url))
    run(git_command(project_dir, "fetch", "--prune", "origin", branch))
    target_revision = git_output(project_dir, "rev-parse", f"origin/{branch}")
    status.update("fetched", "Version distante récupérée", target_revision=target_revision)
    if target_revision == previous_revision:
        status.update("no_update", "Le visualiseur est déjà à jour", current_revision=previous_revision)
        return 0

    try:
        status.update("validating", "Validation de la nouvelle version")
        staging = prepare_staging(project_dir, target_revision)
        install_requirements(staging / "requirements.txt")

        status.update("backing_up", "Sauvegarde de la configuration")
        ensure_backup_space(project_dir, backup_dir)
        run(["systemctl", "stop", "visualizer.service"])
        backup_path = create_backup(project_dir, backup_dir, previous_revision)
        status.update("activating", "Activation de la nouvelle version", backup=str(backup_path))
        activate_revision(project_dir, target_revision, backup_path)
        validate_release(project_dir)

        status.update("health_check", "Redémarrage et contrôle de santé")
        restart_visualizer()
        if not wait_for_health(project_dir):
            raise UpdateError("The updated visualizer did not pass its service and HTTP health checks")

        prune_backups(backup_dir)
        status.update(
            "success",
            "Mise à jour terminée et contrôlée",
            current_revision=target_revision,
            rolled_back=False,
        )
        return 0
    except Exception as update_error:
        if backup_path is None:
            raise
        status.update("rolling_back", "Échec détecté, restauration de l'ancienne version", error=str(update_error))
        try:
            activate_revision(project_dir, previous_revision, backup_path)
            install_requirements(project_dir / "requirements.txt")
            restart_visualizer()
            healthy = wait_for_health(project_dir)
            status.update(
                "rolled_back",
                "Mise à jour annulée, ancienne version restaurée",
                current_revision=previous_revision,
                rolled_back=True,
                rollback_healthy=healthy,
                error=str(update_error),
            )
            return 2
        except Exception as rollback_error:
            raise UpdateError(f"Update failed ({update_error}); rollback also failed ({rollback_error})") from rollback_error
    finally:
        remove_staging(project_dir, staging)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reliably update Piano LED Visualizer")
    parser.add_argument("--project-dir", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--remote-url", default=DEFAULT_REMOTE)
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    project_dir = args.project_dir.resolve()
    args.state_dir.mkdir(parents=True, exist_ok=True)
    lock_path = args.state_dir / "update.lock"
    with lock_path.open("w") as lock_file:
        try:
            if fcntl is not None:
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 3

        status = StatusWriter(args.state_dir / "update-status.json")
        try:
            return perform_update(project_dir, status, args.backup_dir, args.remote_url, args.branch)
        except Exception as error:
            status.update("failed", "La mise à jour a échoué", error=str(error), rolled_back=False)
            try:
                restart_visualizer()
            except Exception:
                pass
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
