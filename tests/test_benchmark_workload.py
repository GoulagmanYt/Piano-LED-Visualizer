import hashlib

import mido
import pytest

from lib.benchmark_workload import transmit, workload
from lib.midi_pipeline_probe import MidiPipelineProbe


def test_deadlines_do_not_drift_when_source_is_stalled():
    now = [10.0]
    emissions = []

    def send(data):
        emissions.append((now[0], data))
        # Simulate a stall longer than two target periods after event one.
        if len(emissions) == 1:
            now[0] += .025

    def sleep(seconds):
        now[0] += seconds

    schedule = [(i * .01, [0x90, 60 + i, 80]) for i in range(4)]
    result = transmit(schedule, send, 10.0, clock=lambda: now[0], sleep=sleep)
    assert [entry[0] for entry in emissions] == pytest.approx([10, 10.025, 10.025, 10.03])
    assert result['sent'] == 4
    assert result['scheduling_lateness_max_ms'] == pytest.approx(15)
    digest = hashlib.sha256()
    for _, data in emissions:
        digest.update(len(data).to_bytes(4, 'big') + bytes(data))
    assert result['hash'] == digest.hexdigest()


@pytest.mark.parametrize('profile', ['chords', 'isolated', 'poisson'])
def test_schedule_is_reproducible_valid_and_releases_every_note(profile):
    events = list(workload(profile, chords=3, duration=10, seed=12))
    assert events == list(workload(profile, chords=3, duration=10, seed=12))
    assert [t for t, _ in events] == sorted(t for t, _ in events)
    active = set()
    for _, data in events:
        message = mido.Message.from_bytes(data)
        if message.type == 'note_on':
            assert message.note not in active
            active.add(message.note)
        elif message.type == 'note_off':
            active.remove(message.note)
    assert not active
    if profile == 'chords':
        assert len(events) == 3 * 26
    if profile == 'isolated':
        assert events[0][0] == 1
        assert events[2][0] - events[1][0] > 1


@pytest.mark.parametrize('rate', [25, 100, 300])
def test_poisson_rate_is_events_per_second(rate):
    events = list(workload('poisson', rate=rate, duration=100, seed=1))
    assert len(events) / 100 == pytest.approx(rate, rel=.1)


@pytest.mark.parametrize('kwargs', [{'profile': 'unknown'}, {'interval': float('nan')},
                                   {'rate': 0}, {'duration': -1}, {'chords': 0}])
def test_invalid_workloads_fail(kwargs):
    with pytest.raises(ValueError):
        next(workload(**kwargs))


def test_probe_includes_source_stall_from_planned_timestamp():
    probe = MidiPipelineProbe()
    message = mido.Message('note_on', note=60)
    probe.sent(message, timestamp=10)
    probe.received(message, timestamp=10.080)
    probe.processed(message)
    probe.forwarded(message, timestamp=10.081)
    report = probe.snapshot()
    assert report['source_to_receive']['max_ms'] == 80
    assert report['source_to_forward']['max_ms'] == 81
    assert report['lossless']
