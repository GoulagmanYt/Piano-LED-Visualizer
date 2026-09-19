#!/usr/bin/env python3

import os
import sys
import unittest
from collections import deque
from unittest.mock import AsyncMock, MagicMock

sys.path.append('./')
sys.path.append('../')

from lib.functions import get_note_position
from lib.queue_utils import drain_deque


class DummyLedStrip:
    def __init__(self, led_number=144, leds_per_meter=72, shift=0, reverse=0):
        self.led_number = led_number
        self.leds_per_meter = leds_per_meter
        self.shift = shift
        self.reverse = reverse


class DummyLedSettings:
    def __init__(self, note_offsets=None):
        self.note_offsets = note_offsets if note_offsets is not None else []


class TestWebsocketDeque(unittest.IsolatedAsyncioTestCase):
    async def test_socket_send_maxlen_and_drain_order(self):
        maxlen = 4096
        total_inserts = 5000
        queue = deque(maxlen=maxlen)

        for i in range(total_inserts):
            queue.append(f"msg-{i}")

        # deque(maxlen=4096) keeps the newest 4096 entries
        self.assertEqual(len(queue), maxlen)
        self.assertEqual(queue[0], "msg-904")
        self.assertEqual(queue[-1], "msg-4999")

        websocket = MagicMock()
        websocket.send = AsyncMock()
        sent = []

        async def _capture(payload):
            sent.append(payload)

        websocket.send.side_effect = _capture

        # Simulate the production loop:
        # while app_state.learning.socket_send:
        #     msg = app_state.learning.socket_send.popleft()
        #     await websocket.send(str(msg))
        while queue:
            msg = queue.popleft()
            await websocket.send(str(msg))

        self.assertEqual(len(queue), 0)
        self.assertEqual(len(sent), maxlen)
        self.assertEqual(sent[0], "msg-904")
        self.assertEqual(sent[-1], "msg-4999")

    async def test_drain_deque_preserves_order_without_slicing(self):
        queue = deque(["a", "b", "c"])
        drained = drain_deque(queue)
        self.assertEqual(drained, ["a", "b", "c"])
        self.assertEqual(len(queue), 0)


class TestLedReverseMapping(unittest.TestCase):
    def test_mapping_is_always_in_bounds_normal_and_reverse(self):
        ledsettings = DummyLedSettings(note_offsets=[])
        led_number = 144
        max_index = led_number - 1

        # note_pos_raw in [-5, 150] -> with density=1, shift=0, no offsets:
        # note_pos_raw = note - 20, so notes in [15, 170]
        notes = range(15, 171)

        for reverse in (0, 1):
            ledstrip = DummyLedStrip(
                led_number=led_number,
                leds_per_meter=72,  # density = 1
                shift=0,
                reverse=reverse,
            )
            for note in notes:
                idx = get_note_position(note, ledstrip, ledsettings)
                self.assertGreaterEqual(idx, 0)
                self.assertLessEqual(idx, max_index)

        # Boundary spot-checks
        normal_strip = DummyLedStrip(led_number=144, leds_per_meter=72, shift=0, reverse=0)
        reverse_strip = DummyLedStrip(led_number=144, leds_per_meter=72, shift=0, reverse=1)

        # note=15 -> raw=-5
        self.assertEqual(get_note_position(15, normal_strip, ledsettings), 0)
        self.assertEqual(get_note_position(15, reverse_strip, ledsettings), 143)

        # note=170 -> raw=150
        self.assertEqual(get_note_position(170, normal_strip, ledsettings), 143)
        self.assertEqual(get_note_position(170, reverse_strip, ledsettings), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
