import importlib
import importlib.util
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from thread_guard import describe, new_live_threads, snapshot, wait_for_exit  # noqa: E402

# lib.log_setup starts a process-lifetime QueueListener thread when imported.
# Import it up front so the first test is not blamed for starting it.
importlib.import_module("lib.log_setup")


def _lcd_hardware_available():
    """tests/test_screen.py drives the real SPI LCD: only collect it on a Pi.

    tests/LCD_Config.py opens /dev/spidev0.0 at import time, so having the
    spidev package installed (CI installs requirements.txt) is not enough.
    """
    if not Path("/dev/spidev0.0").exists():
        return False
    try:
        importlib.import_module("spidev")
        importlib.import_module("RPi.GPIO")
    except Exception:  # ImportError, or RuntimeError when not running on a Pi
        return False
    return True


if not _lcd_hardware_available():
    collect_ignore = ["test_screen.py"]


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "latency: timing-sensitive latency budget (skip with PLV_SKIP_LATENCY=1)"
    )


@pytest.fixture(autouse=True)
def _no_leaked_threads(monkeypatch):
    """Stop MidiPorts workers after each test and fail on any other leaked thread.

    Set PLV_ALLOW_THREAD_LEAKS=1 to downgrade the failure while debugging.
    """
    before = snapshot()
    created = []

    midiports_module = sys.modules.get("lib.midiports")
    if midiports_module is not None:
        original_init = midiports_module.MidiPorts.__init__

        def tracking_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            created.append(self)

        monkeypatch.setattr(midiports_module.MidiPorts, "__init__", tracking_init)

    yield

    for ports in created:
        try:
            ports.close()
        except Exception:
            ports.worker_running = False
            for wake in ("_notify_forward_worker", "_wake_websocket_publish_worker"):
                try:
                    getattr(ports, wake)()
                except Exception:
                    pass

    leaked = wait_for_exit(new_live_threads(before))
    if leaked and os.environ.get("PLV_ALLOW_THREAD_LEAKS") != "1":
        pytest.fail(
            "test leaked live threads: " + describe(leaked)
            + " (join/close them in the test, or set PLV_ALLOW_THREAD_LEAKS=1)",
            pytrace=False,
        )


@pytest.fixture
def player(monkeypatch):
    """Deterministic learning player; hardware and clock are external boundaries."""
    from types import SimpleNamespace
    from unittest.mock import Mock

    from lib import learnmidi
    from lib.midi_queues import MidiQueues

    values = {"hand_colorList": "[[255, 0, 0], [0, 0, 255]]",
              "end_point": "100", "set_tempo": "100", "practice": "2"}
    settings = SimpleNamespace(get_setting_value=lambda key: values.get(key, "0"))
    sent = []
    ports = SimpleNamespace(queues=MidiQueues(), send_all_notes_off=Mock(),
                            schedule_rtp_message=lambda msg, **kw: sent.append((msg.copy(), kw["due_time"])))
    learning = learnmidi.LearnMIDI(settings, Mock(), ports, SimpleNamespace(strip=Mock()))
    learning.loading = 4
    learning.ticks_per_beat = 480
    learning.sent = sent
    learning.socket_send = []
    learning.clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(learnmidi.time, "perf_counter", lambda: learning.clock.now)
    monkeypatch.setattr(learnmidi, "fastColorWipe", lambda *args: None)
    monkeypatch.setattr(learnmidi, "get_note_position", lambda *args: 20)

    def wait(delay):
        learning.clock.now += max(0, delay)
        return learning.stop_event.is_set() or not learning.is_started_midi

    monkeypatch.setattr(learning, "_wait_or_stopped", wait)
    return learning


@pytest.fixture
def song_path(tmp_path, monkeypatch):
    import mido

    monkeypatch.chdir(tmp_path)
    (tmp_path / "Songs").mkdir()
    path = tmp_path / "Songs" / "study.mid"
    song = mido.MidiFile(ticks_per_beat=480)
    song.tracks.append(mido.MidiTrack([mido.Message("note_on", note=60, velocity=90),
                                      mido.Message("note_off", note=60, time=480)]))
    song.save(path)
    return path
