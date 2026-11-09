#!/usr/bin/env python3

import asyncio
import sys
import threading
import time

sys.path.append("./")
sys.path.append("../")

import webinterface as web_mod
from lib.broadcast_outbox import BroadcastOutbox
from webinterface import WakeableDeque, app_state, broadcast_midi_to_clients, webinterface


class FakeSocket:
    def __init__(self):
        self.received = []
        self.received_at = []

    async def send(self, message):
        self.received.append(message)
        self.received_at.append(time.perf_counter())

    async def close(self):
        pass


class StalledSocket(FakeSocket):
    def __init__(self):
        super().__init__()
        self.closed = False

    async def send(self, message):
        await asyncio.sleep(3600)

    async def close(self):
        self.closed = True


class _Learning:
    def __init__(self):
        self.socket_send = BroadcastOutbox()


def _prepare(monkeypatch, clients, poll_interval=0.01):
    queue = WakeableDeque(maxlen=100)
    monkeypatch.setattr(webinterface, "websocket_midi_send", queue)
    monkeypatch.setattr(app_state, "websocket_midi_clients", set(clients))
    monkeypatch.setattr(app_state, "practice_active", True)
    monkeypatch.setattr(app_state, "learning", _Learning())
    monkeypatch.setattr(web_mod, "BROADCAST_POLL_INTERVAL_S", poll_interval)
    return queue


async def _wait_for(predicate, timeout):
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.002)
    return predicate()


def test_wakeable_deque_keeps_deque_behaviour_and_maxlen():
    queue = WakeableDeque(maxlen=3)
    for item in range(5):
        queue.append(item)

    assert queue.maxlen == 3
    assert list(queue) == [2, 3, 4]
    assert queue.popleft() == 2


def test_wakeable_deque_coalesces_wakeups_until_consumed():
    async def scenario():
        loop = asyncio.get_running_loop()
        event = asyncio.Event()
        queue = WakeableDeque(maxlen=100)
        queue.attach_wakeup(loop, event)

        def produce():
            for item in range(50):
                queue.append(item)

        worker = threading.Thread(target=produce)
        worker.start()
        worker.join()
        await asyncio.wait_for(event.wait(), timeout=1)
        assert queue._wake_pending is True
        event.clear()
        queue.consume_wakeup()
        queue.append("again")
        await asyncio.wait_for(event.wait(), timeout=1)

    asyncio.run(scenario())


def test_wakeable_deque_survives_a_closed_loop():
    loop = asyncio.new_event_loop()
    queue = WakeableDeque(maxlen=10)
    queue.attach_wakeup(loop, asyncio.Event())
    loop.close()

    queue.append("late")  # must not raise during shutdown

    assert list(queue) == ["late"]
    assert queue._wake_pending is False


def test_practice_midi_is_delivered_without_waiting_for_the_poll_interval(monkeypatch):
    async def scenario():
        socket = FakeSocket()
        # A 1 s poll would make the old sleep-based loop miss this deadline.
        queue = _prepare(monkeypatch, [socket], poll_interval=1.0)
        wake = asyncio.Event()
        queue.attach_wakeup(asyncio.get_running_loop(), wake)
        task = asyncio.create_task(broadcast_midi_to_clients(wake, send_timeout=1.0))
        await asyncio.sleep(0.05)

        sent_at = time.perf_counter()
        threading.Thread(target=queue.append, args=("midi_event note_on",)).start()
        delivered = await _wait_for(lambda: socket.received, timeout=0.5)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert delivered, "message waited for the poll interval"
        assert socket.received == ["midi_event note_on"]
        assert socket.received_at[0] - sent_at < 0.2

    asyncio.run(scenario())


def test_stalled_client_does_not_freeze_the_other_clients(monkeypatch):
    async def scenario():
        healthy, stalled = FakeSocket(), StalledSocket()
        queue = _prepare(monkeypatch, [healthy, stalled])
        wake = asyncio.Event()
        queue.attach_wakeup(asyncio.get_running_loop(), wake)
        task = asyncio.create_task(broadcast_midi_to_clients(wake, send_timeout=0.1))
        await asyncio.sleep(0.02)

        queue.append("first")
        assert await _wait_for(lambda: healthy.received == ["first"], timeout=1.0)
        assert await _wait_for(lambda: stalled not in app_state.websocket_midi_clients, timeout=1.0)
        assert await _wait_for(lambda: stalled.closed, timeout=1.0)

        queue.append("second")
        assert await _wait_for(lambda: healthy.received == ["first", "second"], timeout=1.0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())


def test_learning_outbox_is_still_delivered_by_the_poll(monkeypatch):
    async def scenario():
        socket = FakeSocket()
        _prepare(monkeypatch, [socket])
        wake = asyncio.Event()
        task = asyncio.create_task(broadcast_midi_to_clients(wake, send_timeout=1.0))

        app_state.learning.socket_send.append('{"loading": 4}')
        assert await _wait_for(lambda: socket.received == ['{"loading": 4}'], timeout=1.0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())


def test_practice_queue_is_left_alone_when_practice_is_inactive(monkeypatch):
    async def scenario():
        socket = FakeSocket()
        queue = _prepare(monkeypatch, [socket])
        monkeypatch.setattr(app_state, "practice_active", False)
        wake = asyncio.Event()
        queue.attach_wakeup(asyncio.get_running_loop(), wake)
        task = asyncio.create_task(broadcast_midi_to_clients(wake, send_timeout=1.0))

        queue.append("ignored")
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert socket.received == []
        assert list(queue) == ["ignored"]

    asyncio.run(scenario())
