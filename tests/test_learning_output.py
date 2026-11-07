import threading

import mido

from lib.learning_output import LearningOutput


class Port:
    def __init__(self):
        self.events = []
        self.closed = False
    def send(self, msg):
        self.events.append(msg)
    def close(self):
        self.closed = True


def test_worker_drains_in_order_before_closing():
    port = Port()
    worker = LearningOutput(port)
    for velocity in (20, 30, 0):
        assert worker.enqueue(mido.Message('note_on', note=60, velocity=velocity))
    assert worker.close()
    assert [msg.velocity for msg in port.events] == [20, 30, 0]
    assert port.closed
    assert not worker.enqueue(mido.Message('note_on', note=60))
    assert worker.close()


def test_send_failure_latches_and_never_replays_stale_notes():
    class FailedPort(Port):
        def send(self, msg):
            if msg.type == 'note_on':
                raise OSError('disconnected')
            super().send(msg)
    port = FailedPort()
    worker = LearningOutput(port)
    worker.enqueue(mido.Message('note_on', note=60, velocity=10))
    worker.enqueue(mido.Message('note_on', note=61, velocity=10))
    assert not worker.close()
    assert isinstance(worker.failure, OSError)
    assert port.closed
    assert all(msg.type == 'control_change' for msg in port.events)
    assert len(port.events) == 48
    assert not worker.enqueue(mido.Message('note_on', note=62))


def test_timeout_does_not_close_port_while_send_is_blocked():
    entered = threading.Event()
    release = threading.Event()
    class BlockingPort(Port):
        def send(self, msg):
            entered.set()
            assert release.wait(5)
            super().send(msg)
    port = BlockingPort()
    worker = LearningOutput(port)
    worker.enqueue(mido.Message('note_on', note=60, velocity=100))
    assert entered.wait(2)
    assert not worker.close(timeout=0.01)
    assert not port.closed
    release.set()
    assert worker.close(timeout=2)
    assert port.closed
