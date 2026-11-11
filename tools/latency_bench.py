#!/usr/bin/env python3
"""Latency micro-benchmarks for the real-time paths (no hardware needed).

    python tools/latency_bench.py            # human readable table
    python tools/latency_bench.py --json     # machine readable

Each benchmark returns millisecond statistics. tests/test_latency_budgets.py
turns them into regression budgets. The budgets are deliberately generous
(several times the measured value) so a loaded CI runner does not flake, yet
they stay far below the pre-optimisation numbers quoted next to them:

    publish worker   mean 4.83 ms / p95 9.66 ms  ->  ~0.07 / ~0.11 ms
    ws broadcast     mean 5.31 ms / p95 9.85 ms  ->  ~0.14 / ~0.19 ms
    change_port      blocks the HTTP request for the whole LCD notice
    stop()           blocked by an LCD notice shown while holding the lock
"""

import argparse
import asyncio
import collections
import json
import random
import statistics
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PLAY_PORT = "rtpmidid:OSCMidiRobin 128:3"


def summarize(samples_ms):
    ordered = sorted(samples_ms)
    if not ordered:
        return {"count": 0, "mean_ms": float("inf"), "p95_ms": float("inf"), "max_ms": float("inf")}
    return {
        "count": len(ordered),
        "mean_ms": statistics.mean(ordered),
        "p95_ms": ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))],
        "max_ms": ordered[-1],
    }


class _Settings:
    def __init__(self, values):
        self.values = dict(values)

    def get_setting_value(self, name):
        return self.values.get(name)

    def change_setting_value(self, name, value):
        self.values[name] = value


class _Port:
    def close(self):
        pass

    def send(self, _msg):
        pass


class _SlowMenu:
    """Behaves like MenuLCD.render_message: sleeps for the notice delay."""

    def __init__(self, delay_scale=1.0):
        self.delay_scale = delay_scale
        self.entered = threading.Event()

    def render_message(self, _title, _message, delay=500):
        self.entered.set()
        time.sleep(delay / 1000.0 * self.delay_scale)

    def show(self):
        pass


def _make_midiports(workers=True):
    from lib.midiports import MidiPorts

    settings = _Settings({"input_port": "default", "play_port": PLAY_PORT})
    with patch("lib.midiports._get_cached_input_names", return_value=[]), patch(
        "lib.midiports._get_cached_output_names", return_value=[PLAY_PORT]
    ), patch("lib.midiports.mido.open_output", return_value=_Port()):
        if workers:
            return MidiPorts(settings)
        with patch.object(MidiPorts, "start_background_workers", lambda self: None):
            return MidiPorts(settings)


class _Recorder(collections.deque):
    """Stands in for webinterface.websocket_midi_send and timestamps appends."""

    def __init__(self):
        super().__init__(maxlen=100000)
        self.stamps = []

    def append(self, item):
        self.stamps.append(time.perf_counter())
        super().append(item)


def measure_publish_latency(notes=120, seed=3):
    """Note queued by the MIDI input -> handed to the websocket broadcaster."""
    import mido

    from webinterface import app_state, webinterface

    ports = _make_midiports(workers=True)
    recorder = _Recorder()
    previous_sink = webinterface.websocket_midi_send
    previous_practice = app_state.practice_active
    webinterface.websocket_midi_send = recorder
    app_state.practice_active = True
    try:
        time.sleep(0.1)  # let the worker go idle
        rnd = random.Random(seed)
        sent = []
        for index in range(notes):
            time.sleep(rnd.uniform(0.002, 0.008))
            sent.append(time.perf_counter())
            ports.queues.enqueue_all_live(
                mido.Message("note_on", note=40 + index % 40, velocity=90), is_note=True
            )
        deadline = time.perf_counter() + 1.0
        while len(recorder.stamps) < notes and time.perf_counter() < deadline:
            time.sleep(0.005)
        result = summarize([(t - s) * 1000 for s, t in zip(sent, recorder.stamps)])
        result["sent"] = notes
        result["published"] = len(recorder.stamps)
        return result
    finally:
        webinterface.websocket_midi_send = previous_sink
        app_state.practice_active = previous_practice
        ports.close()


def measure_broadcast_latency(messages=120, seed=1, use_wakeup=True):
    """Message appended to the websocket queue -> written to the client socket."""
    from webinterface import WakeableDeque, app_state, broadcast_midi_to_clients, webinterface

    class Socket:
        def __init__(self):
            self.stamps = []

        async def send(self, _message):
            self.stamps.append(time.perf_counter())

        async def close(self):
            pass

    async def run():
        socket, queue = Socket(), WakeableDeque(maxlen=100)
        saved = (
            webinterface.websocket_midi_send,
            app_state.websocket_midi_clients,
            app_state.practice_active,
            app_state.learning,
        )
        webinterface.websocket_midi_send = queue
        app_state.websocket_midi_clients = {socket}
        app_state.practice_active = True
        app_state.learning = None
        wake = asyncio.Event() if use_wakeup else None
        if wake is not None:
            queue.attach_wakeup(asyncio.get_running_loop(), wake)
        task = asyncio.create_task(broadcast_midi_to_clients(wake))
        sent = []

        def produce():
            rnd = random.Random(seed)
            for index in range(messages):
                time.sleep(rnd.uniform(0.004, 0.012))
                sent.append(time.perf_counter())
                queue.append(index)

        producer = threading.Thread(target=produce)
        producer.start()
        try:
            while producer.is_alive():
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.1)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            (webinterface.websocket_midi_send, app_state.websocket_midi_clients,
             app_state.practice_active, app_state.learning) = saved
        result = summarize([(t - s) * 1000 for s, t in zip(sent, socket.stamps)])
        result["sent"] = messages
        result["delivered"] = len(socket.stamps)
        return result

    return asyncio.run(run())


def measure_change_port_blocking(async_notice=True, delay_scale=0.1):
    """Time `change_port` keeps its caller (an HTTP request) waiting."""
    ports = _make_midiports(workers=False)
    menu = _SlowMenu(delay_scale=delay_scale)  # 1500 ms notice * scale
    ports.add_instance(menu)
    started = time.perf_counter()
    ports.change_port("playport", "None", async_notice=async_notice)
    return {"blocked_ms": (time.perf_counter() - started) * 1000,
            "notice_ms": 1500 * delay_scale}


def measure_stop_latency(notice_s=0.4):
    """How long stop() waits while an 'Already playing' notice is displayed."""
    from lib.midi_playback_scheduler import MidiPlaybackScheduler, PlaybackState

    class Ports:
        def __init__(self):
            self.midifile_queue = collections.deque()

        def send_all_notes_off(self):
            pass

    class Saving:
        def __init__(self):
            self.is_playing_midi = {}

    menu = _SlowMenu(delay_scale=notice_s / 2.0)  # the notice asks for 2000 ms
    scheduler = MidiPlaybackScheduler(Ports(), Saving(), menu, None, None)
    scheduler.state = PlaybackState.RUNNING
    player = threading.Thread(target=scheduler.play, args=("again.mid",))
    player.start()
    menu.entered.wait(timeout=2)
    started = time.perf_counter()
    scheduler.stop()
    blocked_ms = (time.perf_counter() - started) * 1000
    player.join(timeout=5)
    return {"blocked_ms": blocked_ms, "notice_ms": notice_s * 1000}


def run_all():
    return {
        "publish_worker": measure_publish_latency(),
        "ws_broadcast_wakeup": measure_broadcast_latency(use_wakeup=True),
        "ws_broadcast_poll_10ms": measure_broadcast_latency(use_wakeup=False),
        "change_port_async": measure_change_port_blocking(async_notice=True),
        "change_port_sync": measure_change_port_blocking(async_notice=False),
        "stop_during_notice": measure_stop_latency(),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="print JSON only")
    args = parser.parse_args(argv)
    results = run_all()
    if args.json:
        print(json.dumps(results, indent=2))
        return 0
    for name, stats in results.items():
        print(f"{name:26s} " + "  ".join(f"{k}={v:.2f}" if isinstance(v, float) else f"{k}={v}"
                                          for k, v in stats.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
