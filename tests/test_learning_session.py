from concurrent.futures import ThreadPoolExecutor

import mido

from lib.learning_session import LearningSession


def scene():
    events = []
    def sink(destination):
        return lambda msg, ts: events.append((destination, msg, ts))
    session = LearningSession(guide_sink=sink('guide'), piano_sink=sink('piano'),
                              computer_sink=sink('computer'))
    return session, events


def test_guide_sound_and_echo_are_separated():
    session, events = scene()
    session.route_computer(mido.Message('note_on', note=60, channel=6, velocity=1), 1)
    session.route_piano(mido.Message('note_on', note=60, velocity=90), 2)
    session.route_computer(mido.Message('note_on', note=60, velocity=90), 3)
    session.route_computer(mido.Message('note_on', note=64, channel=2, velocity=80), 4)
    assert [(dest, msg.note) for dest, msg, _ in events] == [
        ('guide', 60), ('computer', 60), ('piano', 64)]


def test_close_silences_both_destinations_and_resets_guides_once():
    session, events = scene()
    session.route_piano(mido.Message('control_change', channel=4, control=64, value=127), 1)
    session.route_piano(mido.Message('note_on', channel=4, note=60, velocity=80), 2)
    session.route_computer(mido.Message('note_on', channel=5, note=65, velocity=80), 3)
    assert session.close(4)
    cleanup = events[3:]
    assert cleanup[0] == ('guide', None, 4)
    assert [(dest, msg.type, msg.channel) for dest, msg, _ in cleanup[1:]] == [
        ('piano', 'note_off', 5), ('computer', 'control_change', 4), ('computer', 'note_off', 4)]
    assert not session.close(5)
    assert not session.route_piano(mido.Message('note_on', note=60), 6)
    assert len(events) == 7


def test_all_notes_off_resets_guides_and_releases_forwarded_sound():
    session, events = scene()
    session.route_computer(mido.Message('note_on', channel=7, note=66, velocity=70), 1)
    session.route_computer(mido.Message('control_change', control=123), 2)
    assert events[1][0] == 'guide' and events[1][1].control == 123
    assert events[2][0] == 'piano' and events[2][1].type == 'note_off'
    assert events[2][1].channel == 7 and events[2][1].note == 66
    session.close(3)
    assert not any(dest == 'piano' for dest, _, _ in events[3:])


def test_control_changes_blocked_by_default():
    session, events = scene()
    session.route_computer(mido.Message('program_change', channel=2, program=10))
    session.route_computer(mido.Message('control_change', control=7, value=100))
    assert events == []


def test_simultaneous_callbacks_do_not_corrupt_note_state():
    session, events = scene()
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda n: session.route_piano(mido.Message('note_on', note=n, velocity=90)), range(48, 80)))
    session.close()
    offs = [msg.note for dest, msg, _ in events if dest == 'computer' and msg.type == 'note_off']
    assert sorted(offs) == list(range(48, 80))


def test_closed_sink_is_reported_to_port_owner():
    import pytest
    session = LearningSession(guide_sink=lambda *args: None,
                              piano_sink=lambda *args: False,
                              computer_sink=lambda *args: None)
    with pytest.raises(RuntimeError, match='not accepting'):
        session.route_computer(mido.Message('note_on', note=60, velocity=90))


def test_close_attempts_both_destinations_even_when_one_fails():
    import pytest
    active = {'fail': False}
    computer = []
    def piano(msg, timestamp):
        return not active['fail']
    session = LearningSession(guide_sink=lambda *args: None, piano_sink=piano,
                              computer_sink=lambda msg, timestamp: computer.append(msg))
    session.route_piano(mido.Message('note_on', channel=2, note=60, velocity=70))
    session.route_computer(mido.Message('note_on', channel=3, note=62, velocity=70))
    active['fail'] = True
    with pytest.raises(RuntimeError, match='not accepting'):
        session.close()
    assert computer[-1].type == 'note_off' and computer[-1].note == 60
    assert not session.close()


def test_same_pitch_on_multiple_channels_releases_each_sound_stream():
    session, events = scene()
    for channel in (2, 3):
        session.route_computer(mido.Message('note_on', channel=channel, note=60, velocity=80))
    for channel in (2, 3):
        session.route_computer(mido.Message('note_on', channel=channel, note=60, velocity=0))
    sent = [msg for dest, msg, _ in events if dest == 'piano']
    assert [(msg.channel, msg.velocity) for msg in sent] == [(2, 80), (3, 80), (2, 0), (3, 0)]
