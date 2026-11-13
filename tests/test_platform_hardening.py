#!/usr/bin/env python3

import subprocess
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import lib.platform as platform_module
from lib.platform import PlatformRasp


# --- connect_to_wifi: never take the hotspot down without a target network ---


class _Recorder(PlatformRasp):
    def __init__(self):
        self.events = []

    def disable_hotspot(self):
        self.events.append("disable_hotspot")

    def enable_hotspot(self, *args, **kwargs):
        self.events.append("enable_hotspot")


@pytest.mark.parametrize("ssid", [None, "", 42])
def test_missing_ssid_leaves_the_hotspot_alone(ssid, monkeypatch):
    platform = _Recorder()
    settings = MagicMock()
    monkeypatch.setattr(
        "lib.platform.subprocess.run", MagicMock(side_effect=AssertionError("nmcli must not run"))
    )

    assert platform.connect_to_wifi(ssid, "secret-password", MagicMock(), settings) is False

    assert platform.events == []
    settings.change_setting_value.assert_not_called()


def test_unexpected_failure_after_the_hotspot_went_down_brings_it_back(monkeypatch):
    platform = _Recorder()
    settings = MagicMock()
    monkeypatch.setattr(
        "lib.platform.subprocess.run", MagicMock(side_effect=OSError("nmcli exploded"))
    )

    assert platform.connect_to_wifi("Home", "secret-password", MagicMock(), settings) is False

    assert platform.events == ["disable_hotspot", "enable_hotspot"]
    settings.change_setting_value.assert_called_with("is_hotspot_active", 1)


# --- change_local_address: only real hostnames, never an option ---------------


@pytest.fixture
def hosts_file(tmp_path, monkeypatch):
    hosts = tmp_path / "hosts"
    hosts.write_text("127.0.0.1\tlocalhost\n127.0.1.1\toldname\n", encoding="utf-8")
    monkeypatch.setattr(platform_module, "HOSTS_FILE", str(hosts))
    return hosts


@pytest.fixture
def commands(monkeypatch):
    run = MagicMock(side_effect=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0))
    monkeypatch.setattr("lib.platform.subprocess.run", run)
    return run


@pytest.mark.parametrize(
    "name",
    ["-h", "--help", "--version", "-abc", "abc-", "", "a b", "a_b", "a.b", "é", "a" * 64],
)
def test_invalid_hostnames_are_rejected_before_anything_runs(name, hosts_file, commands):
    with pytest.raises(ValueError):
        PlatformRasp.change_local_address(name)

    commands.assert_not_called()
    assert "oldname" in hosts_file.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ["pianoled", "a", "A1-b2", "x" * 63, "9lives"])
def test_valid_hostnames_are_applied_everywhere(name, hosts_file, commands):
    assert PlatformRasp.change_local_address(name) is True

    first = commands.call_args_list[0].args[0]
    assert first == ["sudo", "hostnamectl", "set-hostname", name] or first[:3] == [
        "hostnamectl",
        "set-hostname",
        name,
    ]
    assert hosts_file.read_text(encoding="utf-8") == f"127.0.0.1\tlocalhost\n127.0.1.1\t{name}\n"


def test_local_suffix_is_still_stripped(hosts_file, commands):
    assert PlatformRasp.change_local_address("pianoled.local") is True

    assert "127.0.1.1\tpianoled\n" in hosts_file.read_text(encoding="utf-8")


# --- update_visualizer: one updater at a time even with simultaneous clicks ---


def test_simultaneous_update_requests_start_a_single_updater(monkeypatch, tmp_path):
    monkeypatch.setattr(PlatformRasp, "UPDATE_STATE_DIR", tmp_path)
    monkeypatch.setattr("lib.platform.os.geteuid", lambda: 0, raising=False)
    started = []

    def fake_run(command, **kwargs):
        started.append(command)
        return subprocess.CompletedProcess(command, 0, "Running as unit", "")

    monkeypatch.setattr("lib.platform.subprocess.run", fake_run)

    # Widen the window between "read the state" and "mark it as starting" so the
    # race is deterministic instead of a one-in-a-million timing accident.
    real_status = PlatformRasp.get_update_status.__func__

    def slow_status(cls):
        status = real_status(cls)
        time.sleep(0.05)
        return status

    monkeypatch.setattr(PlatformRasp, "get_update_status", classmethod(slow_status))

    barrier = threading.Barrier(6)
    results = []

    def click():
        barrier.wait()
        results.append(PlatformRasp.update_visualizer())

    threads = [threading.Thread(target=click) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(started) == 1, f"{len(started)} updaters were launched"
    assert sum(1 for r in results if r["success"]) == 1
    assert all("déjà en cours" in r["error"] for r in results if not r["success"])


def test_a_failed_launch_does_not_block_the_next_attempt(monkeypatch, tmp_path):
    monkeypatch.setattr(PlatformRasp, "UPDATE_STATE_DIR", tmp_path)
    monkeypatch.setattr("lib.platform.os.geteuid", lambda: 0, raising=False)
    outcomes = iter([1, 0])

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, next(outcomes), "", "boom")

    monkeypatch.setattr("lib.platform.subprocess.run", fake_run)

    assert PlatformRasp.update_visualizer()["success"] is False
    assert PlatformRasp.update_visualizer()["success"] is True
