"""Consumers must not queue behind notification of an already published note."""
import threading
from collections import deque

import mido
import pytest

from lib.midi_queues import MidiQueues


@pytest.mark.parametrize('consumer', ['live', 'learning', 'publish'])
def test_consumers_can_drain_while_callback_signals_activity(consumer):
    queues = MidiQueues()
    notifying = threading.Event()
    release_notification = threading.Event()
    consumed = threading.Event()
    result = []
    note = mido.Message('note_on', note=64, velocity=80)

    class DelayedNotification:
        def is_set(self):
            return False

        def set(self):
            notifying.set()
            assert release_notification.wait(2)

    queues.activity = DelayedNotification()
    producer = threading.Thread(target=queues.enqueue_all_live,
                                args=(note, 1.0), kwargs={'is_note': True})

    def consume():
        if consumer == 'publish':
            result.append(queues.pop_websocket_publish())
        else:
            queue = (queues.live_visualizer_queue if consumer == 'live'
                     else queues.live_learning_queue)
            result.extend(queues.drain_queue(queue))
        consumed.set()

    reader = threading.Thread(target=consume)
    try:
        producer.start()
        assert notifying.wait(1)
        reader.start()
        assert consumed.wait(0.25), 'consumer blocked behind callback notification'
        assert result == [(note, 1.0)]
    finally:
        release_notification.set()
        producer.join(2)
        reader.join(2)


def test_drain_tolerates_queue_becoming_empty_between_pops():
    class ConcurrentlyCleared(deque):
        def popleft(self):
            self.clear()
            return super().popleft()

    # Session changes can clear an input while its previous consumer drains it.
    queues = MidiQueues()
    assert queues.drain_queue(ConcurrentlyCleared([('note', 1.0)])) == []


def test_ui_fanout_cannot_block_forwarding_of_already_admitted_notes():
    queues = MidiQueues()
    publishing = threading.Event()
    release = threading.Event()
    forwarded = threading.Event()
    result = []
    note = mido.Message('note_on', note=60)

    class PausedUiQueue(deque):
        def append(self, value):
            super().append(value)
            publishing.set()
            assert release.wait(2)

    queues.websocket_publish_queue = PausedUiQueue(maxlen=100)
    producer = threading.Thread(target=queues.enqueue_all_live,
                                args=(note, 1.0), kwargs={'is_note': True})

    def forward():
        result.append(queues.peek_live_forward())
        result.append(queues.peek_due_scheduled_forward())
        result.append(queues.peek_next_scheduled_forward())
        result.append(queues.pop_live_forward())
        forwarded.set()

    consumer = threading.Thread(target=forward)
    try:
        producer.start()
        assert publishing.wait(1)
        consumer.start()
        assert forwarded.wait(.25), 'UI fanout delayed the critical forwarding path'
        assert result == [(note, 1.0, 'rtp_rx'), None, None, (note, 1.0, 'rtp_rx')]
    finally:
        release.set()
        producer.join(2)
        consumer.join(2)


def test_activity_notifications_coalesce_until_renderer_consumes_wakeup():
    queues = MidiQueues()

    class CountedEvent(threading.Event):
        notifications = 0

        def set(self):
            self.notifications += 1
            super().set()

    queues.activity = CountedEvent()
    note = mido.Message('note_on', note=60)
    for _ in range(100):
        queues.enqueue_all_live(note)
    assert queues.activity.notifications == 1
    assert len(queues.drain_live_for_visualizer()) == 100
    queues.activity.clear()
    queues.enqueue_all_live(note)
    assert queues.activity.notifications == 2
    assert queues.drain_live_for_visualizer()[0][0] == note
