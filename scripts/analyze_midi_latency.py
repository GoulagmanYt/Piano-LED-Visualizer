#!/usr/bin/env python3
"""Recompute timing statistics from a verified source/arrival JSON capture."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.midi_latency_analysis import analyze


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path,
                        help='Source JSON: events with before_ns, group, pressed')
    parser.add_argument('capture', type=Path,
                        help='Arrival JSON: arrivals_ns and verified run report')
    args = parser.parse_args()
    source = json.loads(args.source.read_text(encoding='utf-8-sig'))
    capture = json.loads(args.capture.read_text(encoding='utf-8-sig'))
    report = capture['report']
    # Exact payload/order validation belongs to the recorder. Never infer event
    # pairing merely because source and receiver packet counts happen to match.
    if report.get('exact_ordered_match') is not True:
        parser.error('Recorder did not verify exact packet identity and order')
    if (report.get('config', {}).get('route', 'production') == 'production'
            and any(report.get('counts', {}).get(key) != len(source['events'])
                    for key in ('midi_callback_calls',
                                'midi_events_processed_total', 'rtp_send_calls'))):
        parser.error('Production counters do not match the source event count')
    try:
        result = analyze(source['events'], capture['arrivals_ns'],
                         report['before_clock'], report['after_clock'])
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
