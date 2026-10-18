"""Offline timing analysis for MIDI captures with verified event alignment.

The caller must establish exact packet identity and order before pairing events.
UDP clock exchanges bound endpoint offset; their midpoint assumes path symmetry.
Interpolating those midpoints estimates offset evolution, not physical clock drift.
This module is diagnostic only and is not imported by the MIDI runtime.
"""
import math
import statistics


def describe(values):
    """Return milliseconds statistics using interpolated sample percentiles."""
    values = sorted(values)
    if not values:
        return {}

    def percentile(q):
        position = (len(values) - 1) * q
        lo, hi = math.floor(position), math.ceil(position)
        return values[lo] + (values[hi] - values[lo]) * (position - lo)

    return {
        key: round(value, 6) for key, value in dict(
            count=len(values), min=values[0], median=percentile(.5),
            mean=statistics.fmean(values), p95=percentile(.95),
            p99=percentile(.99), max=values[-1],
        ).items()
    }


def calibration_anchor(samples):
    """Choose the narrowest exchange bound; offset = source clock - PC clock.

    Each exchange is [PC send, source receive, source send, PC receive], in ns.
    Source processing time is excluded from network RTT and uncertainty.
    """
    valid = [s for s in samples if s[3] - s[0] >= s[2] - s[1] >= 0]
    if not valid:
        raise ValueError('No valid clock exchanges')
    pc_send, source_recv, source_send, pc_recv = min(
        valid, key=lambda s: s[3] - s[0] - (s[2] - s[1]))
    lower, upper = source_send - pc_recv, source_recv - pc_send
    return dict(
        pc_ns=(pc_send + pc_recv) / 2,
        offset_ns=(lower + upper) / 2,
        uncertainty_ns=(upper - lower) / 2,
        samples=len(samples),
        network_rtt_ms=(upper - lower) / 1e6,
    )


def analyze(events, arrivals, before, after):
    """Analyze already matched events; reject missing or reversed timestamps.

    Events contain before_ns, group and pressed. Arrivals are PC monotonic ns.
    Absolute delay uses linearly interpolated clock-offset midpoint estimates.
    Gap errors cancel constant offset; their small slope correction still uses
    the interpolation assumption. Report clock uncertainty alongside all delays.
    """
    if len(events) != len(arrivals) or not events:
        raise ValueError('Exact event alignment required')
    source_times = [event['before_ns'] for event in events]
    if any(b < a for times in (source_times, arrivals)
           for a, b in zip(times, times[1:])):
        raise ValueError('Timestamps must be monotonic in capture order')
    period = after['pc_ns'] - before['pc_ns']
    if period <= 0:
        raise ValueError('Clock anchors must be chronological and distinct')
    slope = (after['offset_ns'] - before['offset_ns']) / period

    def offset(at):
        return before['offset_ns'] + (at - before['pc_ns']) * slope

    latencies = [(arrival - event['before_ns'] + offset(arrival)) / 1e6
                 for event, arrival in zip(events, arrivals)]

    def errors(indices):
        return [((arrivals[b] - arrivals[a]) * (1 + slope)
                 - (source_times[b] - source_times[a])) / 1e6
                for a, b in zip(indices, indices[1:])]

    gap_errors = errors(list(range(len(events))))
    first_ons, chord_indices = {}, {}
    for index, event in enumerate(events):
        if event['pressed']:
            first_ons.setdefault(event['group'], index)
            chord_indices.setdefault(event['group'], []).append(index)
    chord_added, chord_spans = [], []
    for indices in chord_indices.values():
        if len(indices) > 1:
            a, b = indices[0], indices[-1]
            span = (arrivals[b] - arrivals[a]) / 1e6
            chord_spans.append(span)
            chord_added.append(span * (1 + slope)
                               - (source_times[b] - source_times[a]) / 1e6)
    median = statistics.median(latencies)
    return dict(
        latency_ms=describe(latencies),
        clock_uncertainty_ms=max(before['uncertainty_ns'],
                                 after['uncertainty_ns']) / 1e6,
        fitted_clock_offset_slope_ppm=slope * 1e6,
        interval_error_ms=describe(gap_errors),
        absolute_interval_error_ms=describe([abs(v) for v in gap_errors]),
        note_group_interval_error_ms=describe(errors(list(first_ons.values()))),
        chord_arrival_spread_ms=describe(chord_spans),
        chord_added_spread_ms=describe(chord_added),
        late_above_median={str(ms): sum(v > median + ms for v in latencies)
                           for ms in (5, 10, 20, 50)},
        absolute_above_ms={str(ms): sum(v > ms for v in latencies)
                           for ms in (10, 20, 50, 100)},
        worst_events=sorted([
            dict(index=i, group=events[i]['group'], latency_ms=round(value, 4))
            for i, value in enumerate(latencies)
        ], key=lambda v: v['latency_ms'], reverse=True)[:12],
    )
