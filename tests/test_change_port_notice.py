#!/usr/bin/env python3

import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

sys.path.append("./")
sys.path.append("../")

from lib.midiports import MidiPorts
from webinterface import app_state, webinterface

PLAY_PORT = "rtpmidid:OSCMidiRobin 128:3"


class DummySettings:
    def __init__(self, initial):
        self.values = dict(initial)

    def get_setting_value(self, name):
        return self.values.get(name)

    def change_setting_value(self, name, value):
        self.values[name] = value


class DummyPort:
    def close(self):
        pass

    def send(self, _msg):
        pass


class BlockingMenu:
    """Behaves like MenuLCD.render_message: blocks for the display delay."""

    def __init__(self):
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.shown = threading.Event()

    def render_message(self, title, message, delay=500):
        self.calls.append(("render_message", title, message, delay))
        self.entered.set()
        self.release.wait(timeout=10)

    def show(self):
        self.calls.append(("show",))
        self.shown.set()


@pytest.fixture
def midiports(monkeypatch):
    # No forwarding/monitor threads: leaked workers would run under the other
    # tests' global time.perf_counter patches.
    monkeypatch.setattr(MidiPorts, "start_background_workers", lambda self: None)
    settings = DummySettings({"input_port": "default", "play_port": PLAY_PORT})
    with patch("lib.midiports._get_cached_input_names", return_value=[]), patch(
        "lib.midiports._get_cached_output_names", return_value=[PLAY_PORT]
    ), patch("lib.midiports.mido.open_output", return_value=DummyPort()):
        ports = MidiPorts(settings)
    return ports


def test_async_notice_returns_before_the_lcd_notice_ends(midiports):
    menu = BlockingMenu()
    midiports.add_instance(menu)

    started = time.perf_counter()
    midiports.change_port("playport", "None", async_notice=True)
    elapsed = time.perf_counter() - started

    try:
        assert elapsed < 0.5, "change_port waited for the LCD notice"
        assert midiports.usersettings.get_setting_value("play_port") == "None"
        assert midiports.actual_play_port is None
        assert menu.entered.wait(timeout=2)
        assert menu.calls[0] == ("render_message", "Changing playport to:", "None", 1500)
    finally:
        menu.release.set()
    assert menu.shown.wait(timeout=2), "menu was not restored after the notice"
    assert menu.calls[-1] == ("show",)


def test_async_notice_reports_a_failed_change(midiports):
    menu = BlockingMenu()
    midiports.add_instance(menu)

    midiports.change_port("inport", "Missing Piano:Port 20:0", async_notice=True)

    try:
        assert menu.entered.wait(timeout=2)
        assert menu.calls[0][1] == "Can't change inport to:"
    finally:
        menu.release.set()
    assert menu.shown.wait(timeout=2)


def test_default_behaviour_stays_sequential(midiports):
    menu = SimpleNamespace(render_message=Mock(), show=Mock())
    order = []
    menu.render_message.side_effect = lambda *args: order.append("render_message")
    menu.show.side_effect = lambda: order.append("show")
    midiports.add_instance(menu)

    midiports.change_port("playport", "None")

    assert order == ["render_message", "show"]
    menu.render_message.assert_called_once_with("Changing playport to:", "None", 1500)


def test_a_broken_lcd_never_breaks_a_port_change(midiports):
    menu = SimpleNamespace(
        render_message=Mock(side_effect=RuntimeError("LCD unplugged")), show=Mock()
    )
    midiports.add_instance(menu)

    midiports.change_port("playport", "None")  # must not raise

    assert midiports.usersettings.get_setting_value("play_port") == "None"
    assert midiports.actual_play_port is None


def test_port_change_without_a_menu_does_not_raise(midiports):
    midiports.menu = None

    midiports.change_port("playport", "None")
    midiports.change_port("playport", "None", async_notice=True)

    assert midiports.usersettings.get_setting_value("play_port") == "None"


@pytest.fixture
def web_client(monkeypatch):
    values = {}
    menu = SimpleNamespace(last_activity=0, is_idle_animation_running=False)
    settings = SimpleNamespace(
        get_setting_value=values.get, change_setting_value=values.__setitem__
    )
    ports = Mock()
    monkeypatch.setattr(app_state, "menu", menu, raising=False)
    monkeypatch.setattr(app_state, "state_manager", None, raising=False)
    monkeypatch.setattr(app_state, "usersettings", settings, raising=False)
    monkeypatch.setattr(app_state, "midiports", ports, raising=False)
    return SimpleNamespace(client=webinterface.test_client(), ports=ports)


@pytest.mark.parametrize(
    "setting, port", [("input_port", "inport"), ("play_port", "playport")]
)
def test_web_port_change_does_not_wait_for_the_lcd_notice(web_client, setting, port):
    response = web_client.client.get(
        "/api/change_setting", query_string={"setting_name": setting, "value": "None"}
    )

    assert response.status_code == 200
    web_client.ports.change_port.assert_called_once_with(port, "None", async_notice=True)
