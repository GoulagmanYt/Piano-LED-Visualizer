"""Benchmark failures must release the hardware without requiring a real Pi."""

import importlib.util
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def benchmark(monkeypatch):
    # Loading this executable sets argv for VisualizerApp; contain that side effect.
    monkeypatch.setattr(sys, 'argv', list(sys.argv))
    monkeypatch.setattr(sys, 'path', list(sys.path))
    monkeypatch.setitem(sys.modules, 'visualizer', SimpleNamespace(VisualizerApp=Mock()))
    source = Path(__file__).resolve().parents[1] / 'scripts/benchmark_pipeline.py'
    spec = importlib.util.spec_from_file_location('benchmark_cleanup_subject', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def configure_benchmark(module, monkeypatch, failure):
    events = []

    def fail(stage):
        if failure == stage:
            raise RuntimeError(stage)

    output = Mock()
    output.close.side_effect = lambda: (events.append('output.close'), fail('output.close'))
    queues = SimpleNamespace(activity=threading.Event(), set_forwarding_enabled=Mock())
    ports = SimpleNamespace(
        inport=Mock(), playport=Mock(), queues=queues,
        stop_midi_monitor=Mock(return_value=True), _safe_close_port=Mock(),
        _configure_input_backend_filters=Mock(), reset_runtime_diagnostics=Mock(),
        get_runtime_diagnostics=Mock(side_effect=lambda: (fail('diagnostics') or {'queues': {}})),
    )
    strip = Mock()
    strip.getPixels.return_value = []
    app = SimpleNamespace(
        stop_event=threading.Event(), color_mode=SimpleNamespace(MidiEvent=Mock()),
        runtime_diagnostics=SimpleNamespace(snapshot=lambda: {'counters': {}}),
        ci=SimpleNamespace(
            midiports=ports, usersettings=SimpleNamespace(change_setting_value=Mock()),
            ledstrip=SimpleNamespace(strip=strip, keylist=[], keylist_sustained=[]),
            ledsettings=SimpleNamespace(), menu=SimpleNamespace(),
        ),
        run=Mock(side_effect=lambda: fail('run')),
        shutdown=Mock(side_effect=lambda: events.append('app.shutdown')),
    )
    probe = SimpleNamespace(snapshot=lambda: (fail('snapshot') or {'lossless': True}))
    worker = Mock()
    worker.join.side_effect = lambda *args: events.append('worker.join')
    monkeypatch.setattr(module, 'VisualizerApp', lambda: app)
    monkeypatch.setattr(module, 'MidiPipelineProbe', lambda: probe)
    monkeypatch.setattr(module, 'open_midi_input', lambda *args, **kwargs: (fail('input') or Mock()))
    monkeypatch.setattr(module.mido, 'get_output_names', lambda: ['PLV-maintenance-benchmark'])
    monkeypatch.setattr(module.mido, 'open_output', lambda *args: (fail('output') or output))
    monkeypatch.setattr(module.psutil, 'Process', Mock())
    monkeypatch.setattr(module.threading, 'Thread', lambda **kwargs: worker)
    monkeypatch.setattr(module.os, 'sched_getaffinity', lambda pid: {0}, raising=False)
    monkeypatch.setattr(module, 'Path', lambda path: SimpleNamespace(
        read_text=lambda: (fail('proc') or 'clients')))
    monkeypatch.delenv('PLV_BENCHMARK_PROFILE', raising=False)
    return app, output, worker, events


@pytest.mark.parametrize('failure', ['input', 'output', 'run', 'snapshot', 'proc', 'diagnostics', 'output.close'])
def test_benchmark_failure_always_shuts_down_app(benchmark, monkeypatch, failure):
    app, output, _worker, events = configure_benchmark(benchmark, monkeypatch, failure)

    with pytest.raises(RuntimeError, match=failure):
        benchmark.main()

    app.shutdown.assert_called_once()
    if failure in {'input', 'output'}:
        output.close.assert_not_called()
    else:
        output.close.assert_called_once()
        assert events.index('output.close') < events.index('app.shutdown')
        assert app.stop_event.is_set()
        assert app.ci.midiports.queues.activity.is_set()


def test_benchmark_success_shuts_down_before_reporting_black_frame(benchmark, monkeypatch, capsys):
    app, output, _worker, events = configure_benchmark(benchmark, monkeypatch, None)

    def pixels():
        assert events[-1] == 'app.shutdown'
        return []

    app.ci.ledstrip.strip.getPixels.side_effect = pixels
    benchmark.main()

    app.shutdown.assert_called_once()
    output.close.assert_called_once()
    assert '"black_buffer_after_shutdown": true' in capsys.readouterr().out


def test_monitor_timeout_does_not_reassign_live_ports(benchmark, monkeypatch):
    app, output, _worker, _events = configure_benchmark(benchmark, monkeypatch, None)
    app.ci.midiports.stop_midi_monitor.return_value = False

    with pytest.raises(RuntimeError, match='MIDI monitor did not stop'):
        benchmark.main()

    app.ci.midiports._safe_close_port.assert_not_called()
    output.close.assert_not_called()
    app.shutdown.assert_called_once()


def test_benchmark_does_not_persistently_disable_the_configured_rtp_peer(benchmark, monkeypatch):
    app, _output, _worker, _events = configure_benchmark(benchmark, monkeypatch, None)
    benchmark.main()
    app.ci.usersettings.change_setting_value.assert_not_called()


def test_benchmark_construction_does_not_start_network_discovery(benchmark, monkeypatch):
    app, _output, _worker, _events = configure_benchmark(benchmark, monkeypatch, None)
    discoveries = []
    monkeypatch.setattr(benchmark.MidiPorts, 'start_midi_monitor', lambda _ports: discoveries.append('network'))

    def construct():
        benchmark.MidiPorts.start_midi_monitor(object())
        return app

    monkeypatch.setattr(benchmark, 'VisualizerApp', construct)
    benchmark.main()
    assert discoveries == []
    benchmark.MidiPorts.start_midi_monitor(object())
    assert discoveries == ['network']


def test_renderer_failure_interrupts_real_source_worker_before_closing_output(benchmark, monkeypatch):
    real_thread = threading.Thread
    app, output, _worker, events = configure_benchmark(benchmark, monkeypatch, 'run')
    workers = []

    def make_worker(**kwargs):
        worker = real_thread(**kwargs)
        workers.append(worker)
        return worker

    monkeypatch.setattr(benchmark.threading, 'Thread', make_worker)

    with pytest.raises(RuntimeError, match='run'):
        benchmark.main()

    assert workers and not workers[0].is_alive()
    assert app.stop_event.is_set()
    output.send.assert_not_called()
    assert events == ['output.close', 'app.shutdown']


def test_profile_write_failure_still_closes_output_and_app(benchmark, monkeypatch):
    app, output, _worker, _events = configure_benchmark(benchmark, monkeypatch, None)
    profile = Mock()
    profile.dump_stats.side_effect = OSError('profile storage failed')
    monkeypatch.setitem(sys.modules, 'cProfile', SimpleNamespace(Profile=lambda: profile))
    monkeypatch.setenv('PLV_BENCHMARK_PROFILE', 'unused-profile-path')

    with pytest.raises(OSError, match='profile storage failed'):
        benchmark.main()

    output.close.assert_called_once()
    app.shutdown.assert_called_once()
    assert app.stop_event.is_set()
