import io
import subprocess
import tarfile

import pytest

from scripts import reliable_update


def git(project, *args):
    return subprocess.run(
        ["git", "-C", str(project), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def init_repo(project):
    project.mkdir()
    git(project, "init")
    git(project, "config", "user.email", "tests@example.invalid")
    git(project, "config", "user.name", "Tests")
    (project / "config").mkdir()
    (project / "lib").mkdir()
    (project / "webinterface").mkdir()
    (project / "visualizer.py").write_text("print('ok')\n", encoding="utf-8")
    (project / "requirements.txt").write_text("", encoding="utf-8")
    (project / "lib/platform.py").write_text("VALUE = 1\n", encoding="utf-8")
    (project / "webinterface/views_api.py").write_text("VALUE = 1\n", encoding="utf-8")
    (project / "config/sequences.xml").write_text("<sequences/>\n", encoding="utf-8")
    git(project, "add", ".")
    git(project, "commit", "-m", "initial")


def create_update_fixture(tmp_path):
    source = tmp_path / "source"
    init_repo(source)
    git(source, "branch", "-M", "master")
    previous_revision = git(source, "rev-parse", "HEAD")

    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    git(source, "remote", "add", "origin", str(remote))
    git(source, "push", "-u", "origin", "master")

    project = tmp_path / "installed"
    subprocess.run(["git", "clone", "--branch", "master", str(remote), str(project)], check=True, capture_output=True)
    (project / "config/sequences.xml").write_text("<user-sequences/>\n", encoding="utf-8")

    (source / "visualizer.py").write_text("print('new release')\n", encoding="utf-8")
    git(source, "add", "visualizer.py")
    git(source, "commit", "-m", "new release")
    git(source, "push", "origin", "master")
    target_revision = git(source, "rev-parse", "HEAD")
    return project, remote, previous_revision, target_revision


def isolate_system_commands(monkeypatch):
    real_run = reliable_update.run

    def fake_run(command, **kwargs):
        if command[0] == "systemctl":
            return subprocess.CompletedProcess(command, 0, "", "")
        return real_run(command, **kwargs)

    monkeypatch.setattr(reliable_update, "run", fake_run)
    monkeypatch.setattr(reliable_update, "install_requirements", lambda requirements: None)


def test_backup_round_trip_restores_persistent_data(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "config/presets").mkdir(parents=True)
    (project / "Songs").mkdir()
    settings = project / "config/settings.xml"
    preset = project / "config/presets/custom.xml"
    profile = project / "profiles.db"
    song = project / "Songs/user-song.mid"
    settings.write_text("before", encoding="utf-8")
    preset.write_text("preset", encoding="utf-8")
    profile.write_bytes(b"database")
    song.write_bytes(b"midi")

    backup = reliable_update.create_backup(project, tmp_path / "backups", "a" * 40)
    settings.write_text("after", encoding="utf-8")
    preset.unlink()
    profile.unlink()
    song.unlink()
    reliable_update.restore_backup(project, backup)

    assert settings.read_text(encoding="utf-8") == "before"
    assert preset.read_text(encoding="utf-8") == "preset"
    assert profile.read_bytes() == b"database"
    assert song.read_bytes() == b"midi"


def test_restore_rejects_path_traversal(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    archive_path = tmp_path / "bad.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        content = b"unsafe"
        member = tarfile.TarInfo("../outside.txt")
        member.size = len(content)
        archive.addfile(member, io.BytesIO(content))

    with pytest.raises(reliable_update.UpdateError, match="Unsafe backup member"):
        reliable_update.restore_backup(project, archive_path)
    assert not (tmp_path / "outside.txt").exists()


def test_backup_space_check_rejects_insufficient_disk(tmp_path, monkeypatch):
    project = tmp_path / "project"
    (project / "Songs").mkdir(parents=True)
    (project / "Songs/large.mid").write_bytes(b"x" * 1024)
    usage = reliable_update.shutil._ntuple_diskusage(total=2048, used=2048, free=0)
    monkeypatch.setattr(reliable_update.shutil, "disk_usage", lambda path: usage)

    with pytest.raises(reliable_update.UpdateError, match="Not enough space"):
        reliable_update.ensure_backup_space(project, tmp_path / "backups")


def test_changed_source_files_allows_persistent_config_only(tmp_path):
    project = tmp_path / "repo"
    init_repo(project)
    (project / "config/sequences.xml").write_text("<changed/>\n", encoding="utf-8")
    assert reliable_update.changed_source_files(project) == []

    (project / "Songs").mkdir()
    (project / "Songs/example.mid").write_bytes(b"midi")
    git(project, "add", "Songs/example.mid")
    git(project, "commit", "-m", "song")
    (project / "Songs/example.mid").write_bytes(b"changed")
    assert reliable_update.changed_source_files(project) == []

    (project / "visualizer.py").write_text("print('changed')\n", encoding="utf-8")
    assert reliable_update.changed_source_files(project) == ["visualizer.py"]


def test_git_command_scopes_safe_directory_to_repository(tmp_path):
    project = tmp_path / "repo"

    command = reliable_update.git_command(project, "status", "--short")

    assert command[:3] == ["git", "-c", f"safe.directory={project.resolve()}"]
    assert command[3:] == ["-C", str(project.resolve()), "status", "--short"]


def test_validate_release_compiles_required_python_files(tmp_path):
    project = tmp_path / "repo"
    init_repo(project)
    reliable_update.validate_release(project)

    (project / "lib/platform.py").write_text("def broken(:\n", encoding="utf-8")
    with pytest.raises(reliable_update.UpdateError, match="Command failed"):
        reliable_update.validate_release(project)


def test_perform_update_activates_validated_release_and_preserves_config(tmp_path, monkeypatch):
    project, remote, _, target_revision = create_update_fixture(tmp_path)
    isolate_system_commands(monkeypatch)
    monkeypatch.setattr(reliable_update, "wait_for_health", lambda project_dir: True)
    status = reliable_update.StatusWriter(tmp_path / "state/status.json")

    result = reliable_update.perform_update(
        project,
        status,
        tmp_path / "backups",
        str(remote),
        "master",
    )

    assert result == 0
    assert git(project, "rev-parse", "HEAD") == target_revision
    assert (project / "config/sequences.xml").read_text(encoding="utf-8") == "<user-sequences/>\n"
    assert status.payload["state"] == "success"
    assert status.payload["rolled_back"] is False


def test_perform_update_rolls_back_when_health_check_fails(tmp_path, monkeypatch):
    project, remote, previous_revision, _ = create_update_fixture(tmp_path)
    isolate_system_commands(monkeypatch)
    health_results = iter((False, True))
    monkeypatch.setattr(reliable_update, "wait_for_health", lambda project_dir: next(health_results))
    status = reliable_update.StatusWriter(tmp_path / "state/status.json")

    result = reliable_update.perform_update(
        project,
        status,
        tmp_path / "backups",
        str(remote),
        "master",
    )

    assert result == 2
    assert git(project, "rev-parse", "HEAD") == previous_revision
    assert (project / "config/sequences.xml").read_text(encoding="utf-8") == "<user-sequences/>\n"
    assert status.payload["state"] == "rolled_back"
    assert status.payload["rollback_healthy"] is True
