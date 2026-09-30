import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from lib.led_animations import AnimationInfo, AnimationRegistry


def test_restart_waits_for_previous_worker_to_exit():
    registry = AnimationRegistry()
    entered = threading.Event()
    release = threading.Event()
    workers = []

    def animation(strip, settings, menu):
        workers.append(threading.current_thread())
        entered.set()
        release.wait(3)

    registry.register(AnimationInfo("blocked", animation))
    menu = SimpleNamespace(t=None, is_animation_running=False, is_idle_animation_running=False)
    try:
        assert registry.start_animation("blocked", None, None, menu)
        assert entered.wait(1)
        old_worker = menu.t
        assert not registry.start_animation("blocked", None, None, menu)
        assert menu.t is old_worker
        assert not menu.is_animation_running
        assert not menu.is_idle_animation_running
        release.set()
        old_worker.join(1)
        assert not old_worker.is_alive()
        assert registry.start_animation("blocked", None, None, menu)
        menu.t.join(1)
        assert len(workers) == 2
    finally:
        release.set()
        for worker in workers:
            worker.join(1)


@pytest.mark.parametrize("animation_name", ["theaterChase", "rainbow"])
def test_animation_stops_while_cover_remains_closed(monkeypatch, animation_name):
    from lib import functions

    menu = SimpleNamespace(t=threading.current_thread(), is_animation_running=True,
                           is_idle_animation_running=False)
    strip = Mock()
    strip.numPixels.return_value = 10
    ledstrip = SimpleNamespace(strip=strip)
    settings = SimpleNamespace(get_backlight_color=lambda color: 0)
    monkeypatch.setattr(functions, "calculate_brightness", lambda settings: 1)
    monkeypatch.setattr(functions, "fastColorWipe", Mock())
    monkeypatch.setattr(functions.GPIO, "input", lambda pin: 0)
    sleeps = []

    def stop_during_sleep(delay):
        sleeps.append(delay)
        assert len(sleeps) == 1, "worker ignored stop while the cover was closed"
        menu.is_animation_running = False

    monkeypatch.setattr(functions.time, "sleep", stop_during_sleep)
    getattr(functions, animation_name)(ledstrip, settings, menu, speed_ms=10)

    assert sleeps == [0.1]
    strip.show.assert_not_called()
