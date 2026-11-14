#!/usr/bin/env python3
"""Run with the service stopped: ALSA virtual MIDI -> production renderer -> GPIO.

Reports software timing, not physical key-to-photon timing. No MIDI is forwarded
to a piano. Settings are changed only in memory. Always clears LEDs on exit.
"""
import json
import logging
import os
import sys
import threading
import time
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import mido
import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.argv = [str(ROOT / 'visualizer.py'), '-s', '-w', 'false', '-a', 'app']
from lib.buffered_midi_input import open_midi_input
from lib.midi_pipeline_probe import MidiPipelineProbe
from lib.midiports import MidiPorts
from visualizer import VisualizerApp

logger = logging.getLogger(__name__)


class NullOutput:
    def __init__(self, probe):
        self.probe = probe

    def send(self, message):
        self.probe.forwarded(message)

    def close(self):
        pass


class BenchmarkStopped(Exception):
    """The renderer stopped before the source finished sending its workload."""


def stop_worker(app, worker):
    app.stop_event.set()
    app.ci.midiports.queues.activity.set()
    worker.join(3)


def finish_profile(profile):
    profile.disable()
    profile.dump_stats(os.environ['PLV_BENCHMARK_PROFILE'])


def main():
    chord_count = int(os.environ.get('PLV_BENCHMARK_CHORDS', '2000'))
    chord_interval = float(os.environ.get('PLV_BENCHMARK_INTERVAL_MS', '20')) / 1000
    if chord_count < 1 or chord_interval <= 0:
        raise ValueError('Benchmark requires positive chord count and interval')
    probe = MidiPipelineProbe()
    with ExitStack() as cleanup:
        # The benchmark owns its virtual input and instrumented output. Don't
        # start peer discovery/reconnection while constructing those resources.
        with patch.object(MidiPorts, 'start_midi_monitor'):
            app = VisualizerApp()
        cleanup.callback(app.shutdown)
        report = run_benchmark(app, probe, chord_count, chord_interval, cleanup)
    report['black_buffer_after_shutdown'] = not any(app.ci.ledstrip.strip.getPixels())
    print('BENCHMARK_JSON=' + json.dumps(report), flush=True)
    report_queues = report['diagnostics']['queues']
    processed = app.runtime_diagnostics.snapshot()['counters'].get('midi_events_processed_total', 0)
    print('BENCHMARK_PROCESSED=' + str(processed), flush=True)
    if (report['errors'] or report['sent'] != report['received'] or processed != report['received']
            or not report['pipeline']['lossless']
            or any(report_queues.get(q, {}).get('current_depth', 0)
                   for q in ('live_input', 'live_forward', 'scheduled_forward'))
            or report['remaining_keys'] or report['remaining_sustain']
            or not report['black_buffer_after_shutdown']):
        raise SystemExit(1)


def run_benchmark(app, probe, chord_count, chord_interval, cleanup):
    original_midi_event = app.color_mode.MidiEvent

    def trace_processed(message, state, ledstrip):
        original_midi_event(message, state, ledstrip)
        probe.processed(message)

    app.color_mode.MidiEvent = trace_processed
    process = psutil.Process()
    # Stopping the monitor prevents reconnection without persisting changes to
    # the user's configured RTP peer when app.shutdown() saves settings.
    if not app.ci.midiports.stop_midi_monitor():
        raise RuntimeError('MIDI monitor did not stop; benchmark cannot take ownership of its ports')
    app.ci.midiports._safe_close_port(app.ci.midiports.inport)
    app.ci.midiports._safe_close_port(app.ci.midiports.playport)
    app.ci.midiports.playport = NullOutput(probe)
    app.ci.midiports.queues.set_forwarding_enabled(True)
    received = 0
    sent = 0
    samples = []
    errors = []

    recv_by_type = {}
    recv_pedal_channels = []
    def receive(message):
        nonlocal received
        probe.received(message)
        received += 1
        t = message.type
        recv_by_type[t] = recv_by_type.get(t, 0) + 1
        if t == 'control_change' and getattr(message, 'value', None) == 127:
            recv_pedal_channels.append(getattr(message, 'channel', 0))
        app.ci.midiports.msg_callback(message)

    app.ci.midiports.inport = open_midi_input('PLV-maintenance-benchmark', virtual=True, callback=receive)
    app.ci.midiports._configure_input_backend_filters(app.ci.midiports.inport)
    name = next(name for name in mido.get_output_names() if 'PLV-maintenance-benchmark' in name)
    output = mido.open_output(name)
    cleanup.callback(output.close)
    app.ci.ledstrip.strip.setBrightness(12)
    app.ci.ledsettings.backlight_brightness_percent = 0
    app.ci.menu.led_animation_delay = 0
    app.ci.menu.screensaver_delay = '0'
    app.ci.ledsettings.mode = 'Fading'
    app.ci.ledsettings.fadingspeed = 200

    def send(message):
        if app.stop_event.is_set():
            raise BenchmarkStopped
        nonlocal sent
        probe.sent(message)
        output.send(message)
        sent += 1

    def wait(seconds):
        if app.stop_event.wait(seconds):
            raise BenchmarkStopped

    def exercise():
        try:
            wait(3)  # Startup animation settles before measurement.
            # Single RGB cycles at low brightness.
            strip = app.ci.ledstrip.strip
            for color in (0x200000, 0x002000, 0x000020, 0):
                for i in range(strip.numPixels()):
                    strip.setPixelColor(i, color)
                strip.show()
                wait(0.25)
            app.runtime_diagnostics.reset()
            app.ci.midiports.reset_runtime_diagnostics()
            process.cpu_percent()
            measurement_started = time.monotonic()
            # Verify real sustain state, not just transmission of CC64.
            app.ci.ledsettings.mode = 'Pedal'
            send(mido.Message('control_change', control=64, value=127))
            send(mido.Message('note_on', note=60, velocity=80))
            wait(0.1)
            send(mido.Message('note_off', note=60))
            wait(0.1)
            if not any(app.ci.ledstrip.keylist_sustained):
                raise AssertionError('Pedal did not sustain the released note')
            send(mido.Message('control_change', control=64, value=0))
            wait(0.3)
            if any(app.ci.ledstrip.keylist_sustained):
                raise AssertionError('Pedal release left sustained notes')
            app.ci.ledsettings.mode = 'Fading'
            # Single notes include release fades and wakeup from an empty queue.
            for note in range(48, 72):
                send(mido.Message('note_on', note=note, velocity=90))
                wait(0.02)
                send(mido.Message('note_off', note=note))
                wait(0.02)
            # 12-note chords plus sustain: 1,300 events/sec for ~40 sec.
            notes_on = [mido.Message('note_on', note=n, velocity=80) for n in range(48, 60)]
            notes_off = [mido.Message('note_off', note=n) for n in range(48, 60)]
            deadline = time.monotonic()
            for chord in range(chord_count):
                # Pedal and notes belong to the same channel.
                ch = 0
                p_on = mido.Message('control_change', channel=ch, control=64, value=127)
                p_off = mido.Message('control_change', channel=ch, control=64, value=0)
                send(p_on)
                for message in notes_on:
                    send(message)
                for message in notes_off:
                    send(message)
                send(p_off)
                now = time.monotonic()
                if deadline < now:
                    deadline = now + chord_interval
                else:
                    deadline += chord_interval
                wait(max(0.0, deadline - time.monotonic()))
                if chord % 100 == 0:
                    samples.append({'chord': chord, 'elapsed_s': time.monotonic() - measurement_started,
                                    'rss_bytes': process.memory_info().rss,
                                    'cpu_percent': process.cpu_percent()})
            wait(2)
            # A fixed sleep alone can hide a stranded final note or miss a
            # forward backlog. Keep rendering until all three stages drain.
            drain_deadline = time.monotonic() + 5
            while time.monotonic() < drain_deadline:
                if probe.drained:
                    break
                wait(0.01)
        except BenchmarkStopped:
            pass
        except Exception as error:
            logger.exception('Benchmark source failed')
            errors.append(repr(error))
        finally:
            app.stop_event.set()
            app.ci.midiports.queues.activity.set()

    worker = threading.Thread(target=exercise, name='benchmark-source', daemon=True)
    worker.start()
    cleanup.callback(stop_worker, app, worker)
    if os.environ.get('PLV_BENCHMARK_PROFILE'):
        import cProfile
        profile = cProfile.Profile()
        profile.enable()
        cleanup.callback(finish_profile, profile)
    app.run()
    worker.join(3)
    return {'sent': sent, 'received': received, 'recv_by_type': recv_by_type, 'recv_pedals': len(recv_pedal_channels), 'missing_pedals': chord_count + 1 - len(recv_pedal_channels), 'errors': errors, 'samples': samples,
            'pipeline': probe.snapshot(),
            'chord_interval_ms': chord_interval * 1000,
            'led_count': len(app.ci.ledstrip.keylist),
            'cpu_affinity': sorted(os.sched_getaffinity(0)),
            'alsa_clients': Path('/proc/asound/seq/clients').read_text(),
            'diagnostics': app.ci.midiports.get_runtime_diagnostics(),
            'remaining_keys': sum(bool(x) for x in app.ci.ledstrip.keylist),
            'remaining_sustain': sum(bool(x) for x in app.ci.ledstrip.keylist_sustained)}


if __name__ == '__main__':
    main()
