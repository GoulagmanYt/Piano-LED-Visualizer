#!/usr/bin/env python3
"""Run with the service stopped: ALSA virtual MIDI -> production renderer -> GPIO.

Reports software timing, not physical key-to-photon timing. No MIDI is forwarded
to a piano. Settings are changed only in memory. Always clears LEDs on exit.
"""
import hashlib
import json
import logging
import os
import select
import subprocess
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
SOURCE_CPUS = sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else []
WEB = os.environ.get('PLV_BENCHMARK_WEB', 'true')
APPMODE = os.environ.get('PLV_BENCHMARK_APPMODE', 'platform')
sys.argv = [str(ROOT / 'visualizer.py'), '-s', '-w', WEB, '-a', APPMODE]
from lib.benchmark_workload import workload
from lib.buffered_midi_input import open_midi_input
from lib.midi_pipeline_probe import MidiPipelineProbe
from lib.midiports import MidiPorts
from lib.runtime_stalls import RuntimeStallMonitor
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
    if worker.is_alive():
        raise RuntimeError('Benchmark controller did not stop')


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
    source_report = {}
    scheduled = None
    source_epoch = 0.0
    received_hash = hashlib.sha256()
    profile = os.environ.get('PLV_BENCHMARK_WORKLOAD', 'chords')
    workload_config = {'profile': profile, 'chords': chord_count, 'interval': chord_interval,
                           'rate': float(os.environ.get('PLV_BENCHMARK_RATE', '100')),
                           'duration': float(os.environ.get('PLV_BENCHMARK_DURATION', '30')),
                           'seed': int(os.environ.get('PLV_BENCHMARK_SEED', '1'))}
    # Validate before starting any worker.
    if next(workload(**workload_config), None) is None:
        raise ValueError('Benchmark workload contains no events; increase duration')

    recv_by_type = {}
    recv_pedal_channels = []
    def receive(message):
        nonlocal received
        if scheduled is not None:
            # Reconstruct the independent source's intended timestamp lazily.
            # Source count/hash below independently detect missing tail events.
            expected = next(scheduled, None)
            if expected is not None:
                offset, data = expected
                probe.sent_bytes(data, source_epoch + offset)
            encoded = bytes(message.bytes())
            received_hash.update(len(encoded).to_bytes(4, 'big') + encoded)
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
        nonlocal sent, received, scheduled, source_epoch, source_report
        source = None
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
            wait(.3)
            if not probe.drained:
                raise RuntimeError('Warm-up MIDI did not drain')
            # Exclude warm-up and sustain checks from measured workload counts.
            probe.reset()
            sent = received = 0
            recv_by_type.clear()
            recv_pedal_channels.clear()
            app.runtime_diagnostics.reset()
            app.ci.midiports.reset_runtime_diagnostics()
            output.close()
            runtime_cpus = set(os.sched_getaffinity(0))
            other_cpus = [cpu for cpu in SOURCE_CPUS if cpu not in runtime_cpus]
            if not other_cpus:
                raise RuntimeError('No separate source CPU available; expand the launch CPU affinity')
            source_cpu = int(os.environ.get('PLV_BENCHMARK_SOURCE_CPU', other_cpus[0]))
            if source_cpu in runtime_cpus or source_cpu not in SOURCE_CPUS:
                raise ValueError('Source CPU must be allowed and outside the renderer affinity')
            source = subprocess.Popen([sys.executable, str(ROOT / 'scripts/benchmark_source.py')],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True)
            source.stdin.write(json.dumps({'port': name, 'cpu': source_cpu, 'workload': workload_config}) + '\n')
            source.stdin.flush()
            ready_deadline = time.monotonic() + 10
            while not select.select([source.stdout], [], [], .25)[0]:
                if app.stop_event.is_set() or time.monotonic() >= ready_deadline:
                    raise RuntimeError('Independent MIDI source failed to become ready')
            if source.stdout.readline().strip() != 'READY':
                raise RuntimeError('Independent MIDI source failed to become ready')
            scheduled = iter(workload(**workload_config))
            source_epoch = time.perf_counter() + .1
            process.cpu_percent()
            source_deadline = time.monotonic() + max(chord_count * chord_interval,
                                                     workload_config['duration']) + 30
            source_input = str(source_epoch) + '\n'
            while True:
                try:
                    stdout, stderr = source.communicate(input=source_input, timeout=1)
                    break
                except subprocess.TimeoutExpired:
                    source_input = None
                    samples.append({'elapsed_s': time.perf_counter() - source_epoch,
                                        'received': received, 'rss_bytes': process.memory_info().rss,
                                        'cpu_percent': process.cpu_percent()})
                    if app.stop_event.is_set() or time.monotonic() > source_deadline:
                        raise RuntimeError('Independent source stopped or exceeded its deadline')
            if source.returncode:
                raise RuntimeError('Independent MIDI source failed: ' + stderr[-2000:])
            source_report = json.loads(stdout)
            sent = source_report['sent']
            wait(2)
            # A fixed sleep alone can hide a stranded final note or miss a
            # forward backlog. Keep rendering until all three stages drain.
            drain_deadline = time.monotonic() + 5
            while time.monotonic() < drain_deadline:
                if probe.drained:
                    break
                wait(0.01)
            if source_report['hash'] != received_hash.hexdigest() or sent != received:
                raise AssertionError('Independent source and reception count/hash differ')
        except BenchmarkStopped:
            errors.append('Renderer stopped before benchmark workload completed')
        except Exception as error:
            logger.exception('Benchmark source failed')
            errors.append(repr(error))
        finally:
            try:
                if source is not None:
                    if source.poll() is None:
                        source.terminate()
                    try:
                        source.communicate(timeout=1)
                    except subprocess.TimeoutExpired:
                        source.kill()
                        source.communicate(timeout=1)
            except Exception as error:
                logger.exception('Benchmark source cleanup failed')
                errors.append('Source cleanup: ' + repr(error))
            finally:
                app.stop_event.set()
                app.ci.midiports.queues.activity.set()

    worker = threading.Thread(target=exercise, name='benchmark-controller', daemon=True)
    worker.start()
    cleanup.callback(stop_worker, app, worker)
    if os.environ.get('PLV_BENCHMARK_PROFILE'):
        import cProfile
        cpu_profile = cProfile.Profile()
        cpu_profile.enable()
        cleanup.callback(finish_profile, cpu_profile)
    stalls = RuntimeStallMonitor().start() if os.environ.get('PLV_BENCHMARK_STALLS', '1') != '0' else None
    if stalls is not None:
        cleanup.callback(stalls.close)
    app.run()
    worker.join(3)
    if stalls is not None:
        stalls.close()
    pipeline = probe.snapshot()
    if source_report:
        pipeline['source_count_matches'] = sent == received
        pipeline['source_hash_matches'] = source_report['hash'] == received_hash.hexdigest()
        pipeline['lossless'] = (pipeline['lossless'] and pipeline['source_count_matches']
                                and pipeline['source_hash_matches'])
    return {'sent': sent, 'received': received, 'recv_by_type': recv_by_type, 'recv_pedals': len(recv_pedal_channels), 'missing_pedals': (chord_count if profile == 'chords' else 0) - len(recv_pedal_channels), 'errors': errors, 'samples': samples,
            'source': source_report, 'workload': workload_config,
            'latency_origin': 'absolute planned emission; includes source scheduling lateness',
            'web_enabled': WEB != 'false', 'appmode': APPMODE,
            'nice': os.getpriority(os.PRIO_PROCESS, 0) if hasattr(os, 'getpriority') else None,
            'stalls': stalls.snapshot() if stalls is not None else None,
            'led_bulk_upload': getattr(app.ci.ledstrip.strip, '_upload_pixels', None) is not None,
            'fade_interval_ms': float(os.environ.get('PLV_FADE_INTERVAL_MS', '8')),
            'pipeline': pipeline,
            'chord_interval_ms': chord_interval * 1000,
            'led_count': len(app.ci.ledstrip.keylist),
            'cpu_affinity': sorted(os.sched_getaffinity(0)),
            'alsa_clients': Path('/proc/asound/seq/clients').read_text(),
            'diagnostics': app.ci.midiports.get_runtime_diagnostics(),
            'remaining_keys': sum(bool(x) for x in app.ci.ledstrip.keylist),
            'remaining_sustain': sum(bool(x) for x in app.ci.ledstrip.keylist_sustained)}


if __name__ == '__main__':
    main()
