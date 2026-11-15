#!/usr/bin/env python3
"""Validate synthetic RTP/OSC and UDP captures, then plot accepted measurements."""
import argparse
import gzip
import hashlib
import json
import struct
import sys
from itertools import pairwise
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.midi_latency_analysis import analyze, calibration_anchor


def osc_string(value):
    encoded = value.encode() + b'\0'
    return encoded + b'\0' * (-len(encoded) % 4)


def expected_packets(events, route):
    if route == 'raw':
        return [struct.pack('!I', i) + bytes((0x90, e['note'], e['pressed']))
                for i, e in enumerate(events)]
    if route != 'production':
        raise ValueError('Unknown capture route')
    return [osc_string('/avatar/parameters/' + str(e['note'] - 20)) +
            osc_string(',i') + struct.pack('!i', e['pressed']) for e in events]


def packet_hash(packets):
    digest = hashlib.sha256()
    for packet in packets:
        digest.update(len(packet).to_bytes(4, 'big') + packet)
    return digest.hexdigest()


def validate(data, archive):
    if data.get('kind') != 'rtp_end_to_end_capture' or data.get('schema_version') != 1:
        raise ValueError('Unsupported capture dataset')
    if data['record_revision'] != archive['record_revision']:
        raise ValueError('Capture archive version mismatch')
    series = []
    for report in data['runs']:
        capture = archive['runs'][report['label']]
        events, arrivals = capture['events'], capture['arrivals_ns']
        packets = [bytes.fromhex(p) for p in capture['packets_hex']]
        expected = expected_packets(events, report['config']['route'])
        if report['sent'] != len(events) or report['received'] != len(packets) or len(packets) != len(arrivals):
            raise ValueError('Capture count mismatch')
        if packet_hash(expected) != report['source_hash'] or packet_hash(packets) != report['receive_hash']:
            raise ValueError('Capture hash mismatch')
        exact = expected == packets
        if report['exact_ordered_match'] != exact:
            raise ValueError('Incorrect packet identity/order attestation')
        before, after = map(calibration_anchor, capture['calibrations'])
        if before != report['before_clock'] or after != report['after_clock']:
            raise ValueError('Clock anchors do not match exchanges')
        valid = exact and (report['config']['route'] != 'production'
                           or all(report['counts'].get(key) == len(events) for key in
                                  ['midi_callback_calls', 'midi_events_processed_total', 'rtp_send_calls']))
        if report['latency_valid'] != valid:
            raise ValueError('Incorrect latency validity flag')
        if not valid:
            if 'latency_ms' in report:
                raise ValueError('Invalid capture has latency statistics')
            continue
        stats = analyze(events, arrivals, before, after)
        if any(report.get(key) != value for key, value in stats.items()):
            raise ValueError('Published statistics differ from raw capture')
        slope = (after['offset_ns'] - before['offset_ns']) / (after['pc_ns'] - before['pc_ns'])
        latencies = [(arrival - event['before_ns'] + before['offset_ns'] +
                      (arrival - before['pc_ns']) * slope) / 1e6
                     for event, arrival in zip(events, arrivals)]
        series.append({'label': report['label'],
                       'relative_seconds': [(e['before_ns'] - events[0]['before_ns']) / 1e9 for e in events],
                       'source_phase_4s_ms': [(e['before_ns'] / 1e6) % 4000 for e in events],
                       'estimated_latency_ms': latencies,
                       'absolute_interval_error_ms': [abs((b - a) * (1 + slope) -
                           (events[i+1]['before_ns'] - events[i]['before_ns'])) / 1e6
                           for i, (a, b) in enumerate(pairwise(arrivals))]})
    return series


def plot(data, series, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    fig.suptitle(f"RTP/OSCMidi and direct UDP — record {data['record_revision'][:7]}\n"
                 'Three pairs of 6,250 messages; latency statistics require exact delivery and order', fontsize=14)
    reports = data['runs']
    deltas = [r['received'] - r['sent'] for r in reports]
    names = [r['label'].replace('production-', 'RTP ').replace('raw-', 'UDP ') for r in reports]
    colors = ['#0f766e' if r['latency_valid'] else '#b91c1c' for r in reports]
    ax = axes[0, 0]
    ax.bar(names, deltas, color=colors, alpha=.75)
    ax.scatter(names, deltas, color=colors, s=28, zorder=3)
    ax.axhline(0, color='#334155', linewidth=.8)
    for i, (report, delta) in enumerate(zip(reports, deltas)):
        ax.annotate(f"{report['received']:,}/{report['sent']:,}", (i, delta),
                    xytext=(0, -15 if delta < 0 else 8), textcoords='offset points',
                    ha='center', fontsize=8)
    ax.set(title='Delivery check: received minus expected', ylabel='Messages (negative: net shortfall)')
    ax.set_ylim(min(-20, min(deltas) * 1.25), max(50, max(deltas) * 1.3))
    for item in series:
        label = item['label'].replace('raw-', 'Direct UDP ').replace('production-', 'Full RTP ')
        axes[0, 1].scatter(item['relative_seconds'], item['estimated_latency_ms'], s=5, alpha=.55, label=label)
        axes[1, 0].scatter(item['source_phase_4s_ms'], item['estimated_latency_ms'], s=5, alpha=.55, label=label)
        axes[1, 1].scatter(item['relative_seconds'][1:], item['absolute_interval_error_ms'], s=5, alpha=.55, label=label)
    axes[0, 1].set(title='Latency over time — accepted captures only',
                   xlabel='Time since first emission (s)', ylabel='Estimated latency (ms)')
    axes[1, 0].set(title='Latency by Pi clock phase — accepted captures only',
                   xlabel='Pi clock modulo four seconds (ms)', ylabel='Estimated latency (ms)')
    axes[1, 1].set(title='Interval errors — accepted captures only',
                   xlabel='Time since first emission (s)', ylabel='Absolute gap error (ms)')
    for axis in axes.flat:
        axis.grid(axis='y', alpha=.2)
        axis.set_axisbelow(True)
    for axis in [axes[0, 1], axes[1, 0], axes[1, 1]]:
        if series:
            axis.legend(fontsize=9)
        axis.set_ylim(bottom=0)
    uncertainty = max((r['clock_uncertainty_ms'] for r in reports if r['latency_valid']), default=0)
    fig.text(.5, .018,
             f'Absolute latency uses clock-offset interpolation; anchor uncertainty up to ±{uncertainty:.2f} ms.\n'
             'Red delivery bars: failed identity/order/count validation; no deduplication or realignment.\n'
             'RTP: Pi MIDI pipeline → rtpmidid → network → OSCMidi → local OSC. UDP control bypasses MIDI/OSCMidi.',
             ha='center', fontsize=10)
    fig.tight_layout(rect=(0, .095, 1, .94))
    fig.savefig(output, dpi=160)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    data = json.loads(args.dataset.read_text(encoding='utf-8'))
    archive_path = args.dataset.parent / data['capture_archive']
    archive = json.loads(gzip.decompress(archive_path.read_bytes()))
    series = validate(data, archive)
    if args.output:
        plot(data, series, args.output)
    print(f"Verified {len(data['runs'])} captures; {len(series)} pass strict latency validation")


if __name__ == '__main__':
    main()
