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


def test_update_visualizer_pulls_from_maintained_github_remote(monkeypatch):
    calls = []

    monkeypatch.setattr("lib.platform.call", lambda command, shell=True: calls.append(command) or 0)

    PlatformRasp.update_visualizer()

    assert any(
        "git remote set-url origin https://github.com/GoulagmanYt/Piano-LED-Visualizer.git" in command
        for command in calls
    )
    remote_set_index = next(
        index for index, command in enumerate(calls)
        if "git remote set-url origin https://github.com/GoulagmanYt/Piano-LED-Visualizer.git" in command
    )
    pull_index = next(index for index, command in enumerate(calls) if "git pull origin master" in command)
    assert remote_set_index < pull_index
