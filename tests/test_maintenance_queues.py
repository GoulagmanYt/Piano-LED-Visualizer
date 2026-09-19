from types import SimpleNamespace
from lib.midi_queues import MidiQueues


def test_idle_wakeup_and_polyphony_preserve_fifo():
    queues = MidiQueues()
    note = SimpleNamespace(type='note_on', velocity=100)
    off = SimpleNamespace(type='note_off', velocity=0)
    for i in range(10000):
        queues.enqueue_live(note if i % 2 == 0 else off, timestamp=i)
    assert queues.activity.is_set()
    queues.discard_inactive(learning_active=False, live_active=True)
    assert len(queues.live_learning_queue) == 0
    events = queues.drain_live_for_visualizer()
    assert len(events) == 10000
    assert [timestamp for _, timestamp in events] == list(range(10000))
    assert queues.drop_counter == 0


def test_learning_retains_input_but_discards_unused_visualizer_copy():
    queues = MidiQueues()
    note = SimpleNamespace(type='note_on', velocity=100)
    queues.enqueue_live(note)
    queues.discard_inactive(learning_active=True, live_active=False)
    assert queues.live_learning_queue
    assert not queues.live_visualizer_queue
    queues.activity.clear()
    queues.enqueue_file(note)
    assert queues.activity.is_set()
