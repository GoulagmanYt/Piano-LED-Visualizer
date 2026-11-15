import io
import json

from scripts import benchmark_source


def test_source_handshake_and_independent_emission_report(monkeypatch, capsys):
    import mido

    messages = []

    class Output:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def send(self, message):
            messages.append(message)

    config = {'cpu': 1, 'port': 'benchmark', 'workload': {'chords': 1}}
    monkeypatch.setattr(benchmark_source.sys, 'stdin', io.StringIO(json.dumps(config) + '\n10\n'))
    monkeypatch.setattr(mido, 'open_output', lambda name: Output())
    affinities = []
    monkeypatch.setattr(benchmark_source.os, 'sched_setaffinity', lambda pid, cpus: affinities.append(cpus), raising=False)
    monkeypatch.setattr(benchmark_source.os, 'sched_getaffinity', lambda pid: {1}, raising=False)
    monkeypatch.setattr(benchmark_source.os, 'getpriority', lambda *args: -10, raising=False)
    monkeypatch.setattr(benchmark_source.os, 'PRIO_PROCESS', 0, raising=False)
    monkeypatch.setattr(benchmark_source.time, 'perf_counter', lambda: 10.0)
    benchmark_source.main()
    ready, result = capsys.readouterr().out.splitlines()
    report = json.loads(result)
    assert ready == 'READY'
    assert affinities == [{1}]
    assert report['sent'] == len(messages) == 26
    assert report['nice'] == -10
    assert report['cpu_affinity'] == [1]
    assert messages[0] == mido.Message('control_change', control=64, value=127)
    assert messages[-1] == mido.Message('control_change', control=64, value=0)
