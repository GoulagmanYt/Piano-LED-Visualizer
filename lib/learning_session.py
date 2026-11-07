"""Source-aware Learning routing, independent of MIDI port ownership.

The three sinks MUST only enqueue work; they must not call a MIDI port or other
blocking I/O. Input callbacks can call this object concurrently. Decisions and
queue submissions are serialized so a chord's guide events retain their order.
The port owner is responsible for draining output queues to their *old* port
before closing/replacing that port; a session must never be reused across that
transition.
"""
import threading
import time

import mido

from lib.learning_router import ALL_NOTES_OFF, LearningRouter, TO_COMPUTER, TO_LEDS, TO_PIANO


class LearningSession:
    def __init__(self, *, guide_sink, piano_sink, computer_sink, block_control=True, clock=None):
        self._router = LearningRouter(clock=clock)
        self._guide_sink = guide_sink
        self._piano_sink = piano_sink
        self._computer_sink = computer_sink
        self._block_control = bool(block_control)
        self._lock = threading.Lock()
        self._closed = False
        # Track the channels of forwarded notes, unlike the router's note-only
        # echo filter, to send correct cleanup on all MIDI channels.
        self._piano_notes = set()
        self._computer_notes = set()
        self._piano_sustain = set()
        self._computer_sustain = set()

    @staticmethod
    def _enqueue(sink, message, timestamp):
        if sink(message, timestamp) is False:
            raise RuntimeError("Learning MIDI output is not accepting events")

    @staticmethod
    def _track(msg, notes, sustain):
        kind = getattr(msg, 'type', None)
        channel = getattr(msg, 'channel', 0)
        if kind == 'note_on' and msg.velocity > 0:
            notes.add((channel, msg.note))
        elif kind in ('note_on', 'note_off'):
            notes.discard((channel, msg.note))
        elif kind == 'control_change':
            if msg.control == 64:
                if msg.value >= 64:
                    sustain.add(channel)
                else:
                    sustain.discard(channel)
            elif msg.control in ALL_NOTES_OFF:
                notes.difference_update({item for item in notes if item[0] == channel})

    @staticmethod
    def _silence(sink, notes, sustain, timestamp):
        error = None
        messages = [mido.Message('control_change', channel=channel, control=64, value=0)
                    for channel in sorted(sustain)]
        messages += [mido.Message('note_off', channel=channel, note=note, velocity=0)
                     for channel, note in sorted(notes)]
        for msg in messages:
            try:
                LearningSession._enqueue(sink, msg, timestamp)
            except Exception as exc:
                error = error or exc
        notes.clear()
        sustain.clear()
        if error is not None:
            raise error

    def route_piano(self, msg, timestamp=None):
        if timestamp is None:
            timestamp = time.perf_counter()
        with self._lock:
            if self._closed:
                return False
            if self._router.from_piano(msg) & TO_COMPUTER:
                self._enqueue(self._computer_sink, msg, timestamp)
                self._track(msg, self._computer_notes, self._computer_sustain)
            return True

    def route_computer(self, msg, timestamp=None):
        if timestamp is None:
            timestamp = time.perf_counter()
        with self._lock:
            if self._closed:
                return False
            route = self._router.from_computer(msg, self._block_control)
            if route & TO_LEDS:
                # CC 120/123 is consumed as a reset by the guide renderer.
                self._enqueue(self._guide_sink, msg, timestamp)
                for note in self._router.take_led_offs():
                    self._enqueue(self._guide_sink, mido.Message('note_off', channel=0, note=note), timestamp)
            if route & TO_PIANO:
                self._enqueue(self._piano_sink, msg, timestamp)
                self._track(msg, self._piano_notes, self._piano_sustain)
            if (getattr(msg, 'type', None) == 'control_change' and
                    getattr(msg, 'control', None) in ALL_NOTES_OFF):
                # Synthesia resets guide state without forwarding CC 120/123;
                # also release notes we actually forwarded, otherwise they hang.
                self._silence(self._piano_sink, self._piano_notes, self._piano_sustain, timestamp)
                self._router.release_forwarded()
            return True

    def close(self, timestamp=None):
        """End once, queueing guide reset and releases to the existing sinks."""
        if timestamp is None:
            timestamp = time.perf_counter()
        with self._lock:
            if self._closed:
                return False
            self._closed = True
            error = None
            for action in (
                lambda: self._enqueue(self._guide_sink, None, timestamp),
                lambda: self._silence(self._piano_sink, self._piano_notes, self._piano_sustain, timestamp),
                lambda: self._silence(self._computer_sink, self._computer_notes, self._computer_sustain, timestamp),
            ):
                try:
                    action()
                except Exception as exc:
                    error = error or exc
            self._router.reset()
            if error is not None:
                raise error
            return True
