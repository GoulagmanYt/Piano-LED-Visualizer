"""Exact FIFO validation for the opt-in hardware MIDI benchmark."""
from collections import deque
import hashlib
import math
import time


class MidiPipelineProbe:
    def __init__(self):
        self.reset()

    def reset(self):
        """Reset only after the source and consumers have quiesced."""
        self._pending_input = deque()
        self._pending_output = deque()
        self._counts = dict(sent=0, received=0, processed=0, forwarded=0)
        self._hashes = {name: hashlib.sha256() for name in self._counts}
        self.input_order_errors = 0
        self.forward_order_errors = 0
        # Bounded timing samples; counts and hashes cover the entire run.
        self._input_latency = deque(maxlen=100_000)
        self._output_latency = deque(maxlen=100_000)
        self._input_types = deque(maxlen=100_000)
        self._output_types = deque(maxlen=100_000)

    def _record(self, boundary, message):
        data = bytes(message.bytes())
        return self._record_bytes(boundary, data)

    def _record_bytes(self, boundary, data):
        self._counts[boundary] += 1
        self._hashes[boundary].update(len(data).to_bytes(4, 'big') + data)
        return data

    def sent(self, message, timestamp=None):
        timestamp = time.perf_counter() if timestamp is None else timestamp
        self.sent_bytes(message.bytes(), timestamp)

    def sent_bytes(self, data, timestamp):
        """Register a scheduled wire message without reparsing it as MIDI."""
        data = self._record_bytes('sent', bytes(data))
        self._pending_input.append((data, timestamp))

    def received(self, message, timestamp=None):
        timestamp = time.perf_counter() if timestamp is None else timestamp
        data = self._record('received', message)
        try:
            expected, sent_at = self._pending_input.popleft()
        except IndexError:
            expected, sent_at = None, timestamp
        if data != expected:
            self.input_order_errors += 1
        self._input_latency.append(max(0.0, (timestamp - sent_at) * 1000))
        self._input_types.append(message.type)
        self._pending_output.append((data, sent_at))

    def forwarded(self, message, timestamp=None):
        timestamp = time.perf_counter() if timestamp is None else timestamp
        data = self._record('forwarded', message)
        try:
            expected, sent_at = self._pending_output.popleft()
        except IndexError:
            expected, sent_at = None, timestamp
        if data != expected:
            self.forward_order_errors += 1
        self._output_latency.append(max(0.0, (timestamp - sent_at) * 1000))
        self._output_types.append(message.type)

    def processed(self, message):
        self._record('processed', message)

    @property
    def drained(self):
        return (not self._pending_input and not self._pending_output
                and len(set(self._counts.values())) == 1)

    @staticmethod
    def _latency(samples):
        values = sorted(samples)
        if not values:
            return {'samples': 0}
        return dict(samples=len(values), avg_ms=round(sum(values) / len(values), 4),
                    p50_ms=round(values[math.ceil(len(values) * .50) - 1], 4),
                    p95_ms=round(values[math.ceil(len(values) * .95) - 1], 4),
                    p99_ms=round(values[math.ceil(len(values) * .99) - 1], 4),
                    max_ms=round(values[-1], 4))

    def snapshot(self):
        # Call after the source and both consumers have quiesced.
        hashes = {key: value.hexdigest() for key, value in self._hashes.items()}
        def by_type(types, samples):
            groups = {}
            for kind, latency in zip(types, samples):
                groups.setdefault(kind, []).append(latency)
            return {kind: self._latency(values) for kind, values in groups.items()}

        return dict(self._counts, hashes=hashes,
                    latency_sample_limit=self._input_latency.maxlen,
                    latency_sample_scope='latest events; counts and hashes cover the complete run',
                    lossless=(len(set(hashes.values())) == 1
                              and len(set(self._counts.values())) == 1
                              and not self._pending_input and not self._pending_output
                              and not self.input_order_errors and not self.forward_order_errors),
                    input_order_errors=self.input_order_errors,
                    forward_order_errors=self.forward_order_errors,
                    source_to_receive_by_type=by_type(self._input_types, self._input_latency),
                    source_to_forward_by_type=by_type(self._output_types, self._output_latency),
                    source_to_receive=self._latency(self._input_latency),
                    source_to_forward=self._latency(self._output_latency))
