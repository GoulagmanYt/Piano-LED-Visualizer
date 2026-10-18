import mido

from lib.midi_pipeline_probe import MidiPipelineProbe


def test_probe_checks_order_at_both_boundaries_and_reports_latency():
    probe = MidiPipelineProbe()
    messages = [mido.Message('note_on', note=60, velocity=80),
                mido.Message('control_change', control=64, value=127),
                mido.Message('note_on', note=60, velocity=0)]
    for index, message in enumerate(messages):
        probe.sent(message, 10.0 + index)
        probe.received(message, 10.002 + index)
        probe.processed(message)
        probe.forwarded(message, 10.003 + index)
    report = probe.snapshot()
    assert report['lossless']
    assert report['sent'] == report['received'] == report['forwarded'] == 3
    assert report['source_to_receive']['p99_ms'] == 2.0
    assert report['source_to_forward']['max_ms'] == 3.0


def test_same_count_with_reordered_notes_fails_validation():
    probe = MidiPipelineProbe()
    first = mido.Message('note_on', note=60)
    second = mido.Message('note_off', note=60)
    for message in (first, second):
        probe.sent(message, 1.0)
        probe.received(message, 1.1)
        probe.processed(message)
    for message in (second, first):
        probe.forwarded(message, 1.2)
    report = probe.snapshot()
    assert report['sent'] == report['forwarded'] == 2
    assert not report['lossless']
    assert report['forward_order_errors'] == 2


def test_missing_forward_is_not_hidden_by_successful_input_processing():
    probe = MidiPipelineProbe()
    note = mido.Message('note_on', note=60)
    probe.sent(note, 1.0)
    probe.received(note, 1.001)
    probe.processed(note)
    assert not probe.snapshot()['lossless']


def test_missing_input_and_unexpected_output_are_detected():
    probe = MidiPipelineProbe()
    on = mido.Message('note_on', note=60)
    off = mido.Message('note_off', note=60)
    probe.sent(on, 1.0)
    probe.sent(off, 1.0)
    probe.received(off, 1.1)
    probe.forwarded(off, 1.2)
    probe.forwarded(on, 1.2)
    report = probe.snapshot()
    assert not report['lossless']
    assert report['input_order_errors'] == 1
    assert report['forward_order_errors'] == 1


def test_missing_processing_is_not_hidden_by_lossless_forwarding():
    probe = MidiPipelineProbe()
    note = mido.Message('note_on', note=60)
    probe.sent(note, 1.0)
    probe.received(note, 1.001)
    probe.forwarded(note, 1.002)
    assert not probe.snapshot()['lossless']
