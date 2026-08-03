import subprocess

from lib.platform import PlatformRasp


class FakeSettings:
    def __init__(self):
        self.values = {"hotspot_password": "visualizer"}
        self.changes = []

    def get_setting_value(self, name):
        return self.values[name]

    def change_setting_value(self, name, value):
        self.changes.append((name, value))
        self.values[name] = value


class FakeHotspot:
    hotspot_script_time = 0


def test_enable_hotspot_reconciles_profile_before_starting(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        if args[:5] == ["sudo", "nmcli", "connection", "show", "Hotspot"]:
            return subprocess.CompletedProcess(args, 10, "", "not found")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr("lib.platform.subprocess.run", fake_run)

    assert PlatformRasp.enable_hotspot("visualizer") is True

    commands = [call[0] for call in calls]
    assert ["sudo", "nmcli", "connection", "add", "type", "wifi", "ifname", "wlan0",
            "con-name", "Hotspot", "autoconnect", "no", "ssid", "PianoLEDVisualizer"] in commands
    assert ["sudo", "nmcli", "connection", "up", "Hotspot"] == commands[-1]


def test_disconnect_from_wifi_forces_wlan0_to_hotspot(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "Hotspot", "")

    monkeypatch.setattr("lib.platform.subprocess.run", fake_run)
    monkeypatch.setattr("lib.platform.time.time", lambda: 1234)
    monkeypatch.setattr("lib.platform.time.sleep", lambda seconds: None)

    settings = FakeSettings()
    hotspot = FakeHotspot()

    assert PlatformRasp().disconnect_from_wifi(hotspot, settings) is True

    assert hotspot.hotspot_script_time == 1234
    assert ("is_hotspot_active", 1) in settings.changes
    assert ["sudo", "nmcli", "device", "disconnect", "wlan0"] in calls
    assert calls[-1] == ["sudo", "nmcli", "connection", "up", "Hotspot"]


def test_disable_system_midi_scripts_does_not_pass_check_to_subprocess_call(monkeypatch):
    calls = []

    monkeypatch.setattr("lib.platform.os.path.exists", lambda path: path == "/etc/udev/rules.d/33-midiusb.rules")
    monkeypatch.setattr("lib.platform.os.rename", lambda source, target: None)

    def fake_call(args, **kwargs):
        calls.append((args, kwargs))
        return 0

    monkeypatch.setattr("lib.platform.subprocess.call", fake_call)

    PlatformRasp.disable_system_midi_scripts()

    assert calls
    assert all(kwargs == {} for _, kwargs in calls)


def test_update_visualizer_starts_independent_reliable_updater(monkeypatch, tmp_path):
    calls = []

    monkeypatch.setattr(PlatformRasp, "UPDATE_STATE_DIR", tmp_path)
    monkeypatch.setattr("lib.platform.os.geteuid", lambda: 0, raising=False)

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "Running as unit", "")

    monkeypatch.setattr("lib.platform.subprocess.run", fake_run)

    result = PlatformRasp.update_visualizer()

    assert result["success"] is True
    assert len(calls) == 1
    command = calls[0][0]
    assert command[0] == "systemd-run"
    assert any(argument.startswith("--unit=plv-reliable-update-") for argument in command)
    assert "https://github.com/GoulagmanYt/Piano-LED-Visualizer.git" in command
    assert (tmp_path / "update-status.json").exists()


def test_update_visualizer_rejects_concurrent_update(monkeypatch, tmp_path):
    monkeypatch.setattr(PlatformRasp, "UPDATE_STATE_DIR", tmp_path)
    (tmp_path / "update-status.json").write_text(
        '{"state": "validating", "message": "busy"}', encoding="utf-8"
    )

    result = PlatformRasp.update_visualizer()

    assert result["success"] is False
    assert result["state"] == "validating"


def test_update_status_marks_stale_operation_as_failed(monkeypatch, tmp_path):
    monkeypatch.setattr(PlatformRasp, "UPDATE_STATE_DIR", tmp_path)
    (tmp_path / "update-status.json").write_text(
        '{"state": "health_check", "message": "busy", "updated_at": 1}', encoding="utf-8"
    )

    status = PlatformRasp.get_update_status()

    assert status["state"] == "failed"
    assert "interrompue" in status["message"]
