"""Validate captures from an external sensor using one acquisition clock."""

import math


def _integer(value):
    if isinstance(value, str):
        if not value.isascii() or not value.isdecimal() or len(value) > 20:
            raise ValueError("Capture integers must be unsigned decimal nanoseconds/IDs")
        value = int(value)
    if type(value) is not int or not 0 <= value <= 2**64 - 1:
        raise ValueError("Capture value is not an unsigned 64-bit integer")
    return value


def analyze_capture(rows, expected_events):
    """Rows are in acquisition order; never realign missing or reordered events.

    The caller must establish that trigger and response are real sensor edges,
    paired correctly and sampled by the same clock. Software cannot attest that.
    """
    if type(expected_events) is not int or expected_events < 1:
        raise ValueError("expected_events must be a positive integer")
    if len(rows) != expected_events:
        raise ValueError("Incomplete capture: observed count differs from expected count")
    delays = []
    clock = None
    previous_trigger = previous_response = -1
    for index, row in enumerate(rows):
        try:
            event_id = _integer(row["event_id"])
            trigger = _integer(row["trigger_ns"])
            response = _integer(row["response_ns"])
            row_clock = row["clock_id"]
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"Invalid capture row {index}") from error
        if event_id != index:
            raise ValueError("Capture event identity/order failed")
        if not isinstance(row_clock, str) or not row_clock.strip():
            raise ValueError("Each row requires a nonempty acquisition clock_id")
        if clock is None:
            clock = row_clock
        elif row_clock != clock:
            raise ValueError("Trigger/response capture must use one acquisition clock")
        if trigger < 0 or trigger <= previous_trigger or response < trigger or response < previous_response:
            raise ValueError("Capture timestamps are negative, reversed or out of order")
        previous_trigger, previous_response = trigger, response
        delays.append((response - trigger) / 1_000_000)
    ordered = sorted(delays)

    def percentile(fraction):
        position = (len(ordered) - 1) * fraction
        lower = math.floor(position)
        upper = math.ceil(position)
        return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)

    return {
        "events": expected_events, "clock_id": clock,
        "capture_complete": True, "sensor_and_pairing_verified_by_tool": False,
        "mean_ms": math.fsum(delays) / len(delays), "median_ms": percentile(0.5),
        "p95_ms": percentile(0.95), "p99_ms": percentile(0.99),
        "min_ms": ordered[0], "max_ms": ordered[-1],
    }
