#!/usr/bin/env python3
"""Run with the service stopped: ALSA virtual MIDI -> production renderer -> GPIO.

Reports software timing, not physical key-to-photon timing. No MIDI is forwarded
to a piano. Settings are changed only in memory. Always clears LEDs on exit.
"""
import json
import os
from pathlib import Path
import sys
import threading
import time

import mido
import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.argv = [str(ROOT / 'visualizer.py'), '-s', '-w', 'false', '-a', 'app']
from visualizer import VisualizerApp


class NullOutput:
    def send(self, message):
        pass

    def close(self):
        pass


def main():
    chord_count = int(os.environ.get('PLV_BENCHMARK_CHORDS', '2000'))
    app = VisualizerApp()
    process = psutil.Process()
    app.ci.midiports.stop_midi_monitor()
    app.ci.midiports._safe_close_port(app.ci.midiports.inport)
    app.ci.midiports._safe_close_port(app.ci.midiports.playport)
    app.ci.midiports.playport = NullOutput()
    app.ci.midiports.queues.set_forwarding_enabled(True)
    received = 0
    sent = 0
    samples = []
    errors = []

    recv_by_type = {}
    recv_pedal_channels = []
    def receive(message):
        nonlocal received
        received += 1
        t = message.type
        recv_by_type[t] = recv_by_type.get(t, 0) + 1
        if t == 'control_change' and getattr(message, 'value', None) == 127:
            recv_pedal_channels.append(getattr(message, 'channel', 0))
        app.ci.midiports.msg_callback(message)

    app.ci.midiports.inport = mido.open_input('PLV-maintenance-benchmark', virtual=True, callback=receive)
    app.ci.midiports._configure_input_backend_filters(app.ci.midiports.inport)
    name = next(name for name in mido.get_output_names() if 'PLV-maintenance-benchmark' in name)
    output = mido.open_output(name)
    app.ci.ledstrip.strip.setBrightness(12)
    app.ci.ledsettings.backlight_brightness_percent = 0
    app.ci.menu.led_animation_delay = 0
    app.ci.menu.screensaver_delay = '0'
    app.ci.ledsettings.mode = 'Fading'
    app.ci.ledsettings.fadingspeed = 200

    def send(message):
        nonlocal sent
        output.send(message)
        sent += 1

    def exercise():
        try:
            time.sleep(3)  # Startup animation settles before measurement.
            # Single RGB cycles at low brightness.
            strip = app.ci.ledstrip.strip
            for color in (0x200000, 0x002000, 0x000020, 0):
                for i in range(strip.numPixels()):
                    strip.setPixelColor(i, color)
                strip.show()
                time.sleep(0.25)
            app.runtime_diagnostics.reset()
            app.ci.midiports.reset_runtime_diagnostics()
            process.cpu_percent()
            # Verify real sustain state, not just transmission of CC64.
            app.ci.ledsettings.mode = 'Pedal'
            send(mido.Message('control_change', control=64, value=127))
            send(mido.Message('note_on', note=60, velocity=80))
            time.sleep(0.1)
            send(mido.Message('note_off', note=60))
            time.sleep(0.1)
            if not any(app.ci.ledstrip.keylist_sustained):
                raise AssertionError('Pedal did not sustain the released note')
            send(mido.Message('control_change', control=64, value=0))
            time.sleep(0.3)
            if any(app.ci.ledstrip.keylist_sustained):
                raise AssertionError('Pedal release left sustained notes')
            app.ci.ledsettings.mode = 'Fading'
            # Single notes include release fades and wakeup from an empty queue.
            for note in range(48, 72):
                send(mido.Message('note_on', note=note, velocity=90))
                time.sleep(0.02)
                send(mido.Message('note_off', note=note))
                time.sleep(0.02)
            # 12-note chords plus sustain: 1,300 events/sec for ~40 sec.
            notes_on = [mido.Message('note_on', note=n, velocity=80) for n in range(48, 60)]
            notes_off = [mido.Message('note_off', note=n) for n in range(48, 60)]
            pedal_on = mido.Message('control_change', control=64, value=127)
            pedal_off = mido.Message('control_change', control=64, value=0)
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
                    deadline = now + 0.02
                else:
                    deadline += 0.02
                time.sleep(max(0.005, deadline - time.monotonic()))
                if chord % 100 == 0:
                    samples.append({'chord': chord, 'rss_bytes': process.memory_info().rss,
                                    'cpu_percent': process.cpu_percent()})
            time.sleep(2)
        except Exception as error:
            errors.append(repr(error))
        finally:
            app.stop_event.set()
            app.ci.midiports.queues.activity.set()

    worker = threading.Thread(target=exercise, name='benchmark-source', daemon=True)
    worker.start()
    profile = None
    if os.environ.get('PLV_BENCHMARK_PROFILE'):
        import cProfile
        profile = cProfile.Profile()
        profile.enable()
    try:
        app.run()
    finally:
        if profile is not None:
            profile.disable()
            profile.dump_stats(os.environ['PLV_BENCHMARK_PROFILE'])
        worker.join(3)
        output.close()
        report = {'sent': sent, 'received': received, 'recv_by_type': recv_by_type, 'recv_pedals': len(recv_pedal_channels), 'missing_pedals': chord_count + 1 - len(recv_pedal_channels), 'errors': errors, 'samples': samples,
                  'diagnostics': app.ci.midiports.get_runtime_diagnostics(),
                  'remaining_keys': sum(bool(x) for x in app.ci.ledstrip.keylist),
                  'remaining_sustain': sum(bool(x) for x in app.ci.ledstrip.keylist_sustained)}
        app.shutdown()
        report['black_buffer_after_shutdown'] = not any(app.ci.ledstrip.strip.getPixels())
        print('BENCHMARK_JSON=' + json.dumps(report), flush=True)
    report_queues = report['diagnostics']['queues']
    processed = app.runtime_diagnostics.snapshot()['counters'].get('midi_events_processed_total', 0)
    print('BENCHMARK_PROCESSED=' + str(processed), flush=True)
    if (errors or sent != received or processed != received
            or any(report_queues.get(q, {}).get('current_depth', 0)
                   for q in ('live_input', 'live_forward', 'scheduled_forward'))
            or report['remaining_keys'] or report['remaining_sustain']
            or not report['black_buffer_after_shutdown']):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
