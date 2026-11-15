#!/usr/bin/env python3
"""Validate a published Pi A/B dataset and plot its per-run observations.

Matplotlib is required only for --output; --summary uses the standard library.
"""
import argparse
import json
import math
from pathlib import Path
from statistics import fmean, median

CONFIGS = [(0, 0), (1, 0), (0, 8), (1, 8)]
LABELS = ['Setters\nfade 0 ms', 'Bulk\nfade 0 ms',
          'Setters\nfade 8 ms', 'Bulk\nfade 8 ms']


def summarize_run(run):
    """Use whole-run timing means and CPU intervals inside source emission."""
    report, config = run['report'], run['config']
    pipeline, source = report['pipeline'], report['source']
    if run['returncode'] or report['errors'] or not pipeline['lossless']:
        raise ValueError(f"Failed benchmark: {run['name']}")
    if pipeline['input_order_errors'] or pipeline['forward_order_errors']:
        raise ValueError(f"Message ordering error: {run['name']}")
    if not (report['sent'] == report['received'] == source['sent'] == pipeline['processed']
            == pipeline['forwarded'] == pipeline['sent'] == pipeline['received']):
        raise ValueError(f"Event count mismatch: {run['name']}")
    if not pipeline['source_count_matches'] or not pipeline['source_hash_matches']:
        raise ValueError(f"Independent source mismatch: {run['name']}")
    if set(pipeline['hashes'].values()) != {source['hash']}:
        raise ValueError(f"Message hash mismatch: {run['name']}")
    if report['led_bulk_upload'] != bool(config['bulk']) or report['fade_interval_ms'] != config['fade']:
        raise ValueError(f"Requested LED path not selected: {run['name']}")
    if report['led_count'] != 195 or report['workload']['profile'] != config['workload']:
        raise ValueError(f"Inconsistent hardware or workload: {run['name']}")
    if config['workload'] == 'chords' and (report['workload']['chords'] != 2000
            or report['workload']['interval'] != .02 or report['received'] != 52000):
        raise ValueError(f"Inconsistent chord schedule: {run['name']}")
    if (report['cpu_affinity'] != [2] or source['cpu_affinity'] != [1]
            or report['nice'] != -10 or source['nice'] != -10
            or not report['web_enabled'] or report['appmode'] != 'platform'):
        raise ValueError(f"Inconsistent benchmark conditions: {run['name']}")
    if bool(report['stalls'] is not None) != bool(config['stalls']):
        raise ValueError(f"Inconsistent monitor setting: {run['name']}")
    if report['remaining_keys'] or report['remaining_sustain'] or not report['black_buffer_after_shutdown']:
        raise ValueError(f"Incomplete shutdown: {run['name']}")
    if any(report['diagnostics']['queues'][name]['current_depth']
           for name in ['live_input', 'live_forward', 'scheduled_forward']):
        raise ValueError(f"Undrained queue: {run['name']}")
    timings = report['diagnostics']['timings']
    samples = [s for s in run['main_thread_samples']
               if source['epoch'] <= s['start_perf'] < s['end_perf'] <= source['last_send']]
    duration = sum(s['end_perf'] - s['start_perf'] for s in samples)
    if not samples or duration <= 0:
        raise ValueError(f"No main-thread CPU samples: {run['name']}")
    summary = {
        'name': run['name'], **config, 'events': report['received'],
        'forward': pipeline['source_to_forward'],
        'note_on_receive': pipeline['source_to_receive_by_type']['note_on'],
        'note_on_forward': pipeline['source_to_forward_by_type']['note_on'],
        'upload_ms': timings['led_pixel_upload']['avg_ms'],
        'fade_ms': timings['process_fade_effects']['avg_ms'],
        'main_loop_ms': timings['main_loop']['avg_ms'],
        'main_loop_count': timings['main_loop']['count'],
        'loops_per_chord': (timings['main_loop']['count'] / report['workload']['chords']
                            if config['workload'] == 'chords' else None),
        'process_cpu_percent': fmean(s['cpu_percent'] for s in report['samples']),
        'main_cpu_percent': sum(s['main_cpu_percent'] * (s['end_perf'] - s['start_perf'])
                                for s in samples) / duration,
        'main_cpu_sampled_s': duration,
        'source_lateness_avg_ms': source['scheduling_lateness_avg_ms'],
        'source_lateness_max_ms': source['scheduling_lateness_max_ms'],
        'gc_count': report['stalls']['gc_count'] if report['stalls'] else None,
        'stall_count': report['stalls']['stall_count'] if report['stalls'] else None,
    }
    if any(not math.isfinite(summary[key]) for key in
           ['upload_ms', 'fade_ms', 'main_loop_ms', 'process_cpu_percent', 'main_cpu_percent']):
        raise ValueError(f"Non-finite measurement: {run['name']}")
    return summary


def summarize(data):
    if data.get('kind') != 'led_bulk_fade_matrix' or data.get('schema_version') != 2:
        raise ValueError('Expected a version 2 LED bulk/fade matrix dataset')
    if not data.get('complete') or not data.get('production_config_unchanged'):
        raise ValueError('Campaign incomplete or production settings changed')
    rows = [summarize_run(run) for run in data['runs']]
    for config in CONFIGS:
        subset = [r for r in rows if r['group'] == 'matrix' and (r['bulk'], r['fade']) == config]
        if len(subset) != 5 or {r['repeat'] for r in subset} != set(range(1, 6)):
            raise ValueError(f'Expected five independent runs for configuration {config}')
    return rows


def plot(data, rows, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    matrix = [r for r in rows if r['group'] == 'matrix']
    groups = [[r for r in matrix if (r['bulk'], r['fade']) == config] for config in CONFIGS]
    fig, axes = plt.subplots(2, 3, figsize=(15, 9))
    fig.suptitle(f"LED bulk upload and fade cadence — {data['measured_at_utc'][:10]}\n"
                 f"{data['board']} · {data['revision'][:7]} · 5 runs/configuration · 52,000 events/run", fontsize=15)
    metrics = [
        ('MIDI thru p99', lambda r: r['forward']['p99_ms'], 'Planned source → output (ms)'),
        ('MIDI thru maximum', lambda r: r['forward']['max_ms'], 'Planned source → output (ms)'),
        ('Mean pixel upload time', lambda r: 1000 * r['upload_ms'], 'Microseconds/frame'),
        ('Mean main-thread CPU\nduring source emission', lambda r: r['main_cpu_percent'], '% of one CPU core'),
        ('Mean fade processing time\nper recorded pass', lambda r: r['fade_ms'], 'Milliseconds/pass'),
        ('Recorded main-loop iterations\nper requested chord', lambda r: r['loops_per_chord'], 'Iterations/chord (includes drain)'),
    ]
    colors = ['#64748b', '#2563eb', '#0f766e', '#7c3aed']
    for ax, (title, extract, ylabel) in zip(axes.flat, metrics):
        for i, group in enumerate(groups):
            values = [extract(r) for r in group]
            ax.bar(i, median(values), width=.62, color=colors[i], alpha=.22)
            ax.scatter([i + .035 * (r['repeat'] - 3) for r in group], values,
                       color=colors[i], s=30, zorder=3)
        ax.set(title=title, ylabel=ylabel, xticks=range(4), xticklabels=LABELS)
        ax.set_ylim(bottom=0)
        ax.grid(axis='y', alpha=.2)
        ax.set_axisbelow(True)
        if 'CPU' in title:
            ax.set_ylim(top=max(100, ax.get_ylim()[1]))
    fig.text(.5, .015,
             'Dots: individual runs; translucent bars: median of run values. Canary enabled throughout.\n'
             'Runtime CPU 2; source CPU 1; external sampler CPU 3; nice −10; web/LCD enabled.\n'
             'Software boundaries with real GPIO/DMA and instrumented MIDI output; no key/light/audio sensor.',
             ha='center', fontsize=10)
    fig.tight_layout(rect=(0, .09, 1, .95), h_pad=2.5)
    fig.savefig(output, dpi=160)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset', type=Path)
    parser.add_argument('--output', type=Path, help='Chart path, for example a PNG or SVG')
    parser.add_argument('--summary', type=Path, help='Write validated per-run statistics as JSON')
    args = parser.parse_args()
    data = json.loads(args.dataset.read_text(encoding='utf-8'))
    rows = summarize(data)
    if args.summary:
        args.summary.write_text(json.dumps(rows, indent=2) + '\n', encoding='utf-8')
    if args.output:
        plot(data, rows, args.output)
    print(f"Validated {len(rows)} benchmark runs from {args.dataset}")


if __name__ == '__main__':
    main()
