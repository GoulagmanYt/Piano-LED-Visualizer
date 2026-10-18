import unittest
import json
from pathlib import Path
import subprocess
import sys
from lib.midi_latency_analysis import analyze, calibration_anchor

class TimingTests(unittest.TestCase):
    def test_clock_bound_accounts_for_server_processing(self):
        # Pi clock is 1 s ahead, paths each take 2 ms, server takes 1 ms.
        sample=[0,1_002_000_000,1_003_000_000,5_000_000]
        a=calibration_anchor([sample])
        self.assertEqual(a['offset_ns'],1_000_000_000)
        self.assertEqual(a['uncertainty_ns'],2_000_000)

    def test_constant_delay_preserves_source_spacing_and_chord_spread(self):
        events=[dict(before_ns=1_000_000_000+i*1_000_000,group=i//2,pressed=1) for i in range(4)]
        arrivals=[8_000_000+i*1_000_000 for i in range(4)]
        anchor=dict(pc_ns=0,offset_ns=1_000_000_000,uncertainty_ns=100_000)
        result=analyze(events,arrivals,anchor,dict(anchor,pc_ns=100_000_000))
        self.assertEqual(result['latency_ms']['median'],8)
        self.assertEqual(result['interval_error_ms']['max'],0)
        self.assertEqual(result['chord_added_spread_ms']['max'],0)

    def test_delayed_message_is_visible_as_stretch_and_compression(self):
        events=[dict(before_ns=i*10_000_000,group=i,pressed=1) for i in range(4)]
        arrivals=[5_000_000,15_000_000,45_000_000,46_000_000]
        anchor=dict(pc_ns=0,offset_ns=0,uncertainty_ns=1)
        result=analyze(events,arrivals,anchor,dict(anchor,pc_ns=100_000_000))
        self.assertEqual(result['interval_error_ms']['max'],20)
        self.assertEqual(result['interval_error_ms']['min'],-9)
        self.assertEqual(result['latency_ms']['max'],25)

    def test_shifted_message_indices_are_rejected(self):
        anchor=dict(pc_ns=0,offset_ns=0,uncertainty_ns=0)
        with self.assertRaises(ValueError): analyze([{}],[],anchor,anchor)

    def test_calibration_chooses_narrowest_network_bound(self):
        result = calibration_anchor([
            [0, 1_009_000_000, 1_010_000_000, 11_000_000],
            [20_000_000, 1_022_000_000, 1_023_000_000, 25_000_000],
        ])
        self.assertEqual(result['offset_ns'], 1_000_000_000)
        self.assertEqual(result['uncertainty_ns'], 2_000_000)

    def test_reversed_capture_timestamps_are_rejected(self):
        anchor = dict(pc_ns=0, offset_ns=0, uncertainty_ns=1)
        end = dict(anchor, pc_ns=100_000_000)
        events = [dict(before_ns=i, group=i, pressed=1) for i in (0, 1)]
        with self.assertRaisesRegex(ValueError, 'monotonic'):
            analyze(events, [2, 1], anchor, end)
        with self.assertRaisesRegex(ValueError, 'chronological'):
            analyze(events, [1, 2], end, anchor)

    def test_clock_offset_evolution_does_not_create_false_gap_error(self):
        # Source clock runs 100 ppm faster: 10 ms there = 9.999 ms on PC.
        events = [dict(before_ns=1_000_000_000 + i * 10_001_000,
                       group=i, pressed=1) for i in range(4)]
        arrivals = [i * 10_000_000 for i in range(4)]
        before = dict(pc_ns=0, offset_ns=1_005_000_000, uncertainty_ns=1)
        after = dict(before, pc_ns=100_000_000, offset_ns=1_005_010_000)
        result = analyze(events, arrivals, before, after)
        self.assertEqual(result['latency_ms']['min'], 5)
        self.assertEqual(result['latency_ms']['max'], 5)
        self.assertEqual(result['absolute_interval_error_ms']['max'], 0)

if __name__=='__main__': unittest.main()


def test_cli_checks_legacy_production_counters_when_route_is_omitted(tmp_path):
    source = tmp_path / 'source.json'
    capture = tmp_path / 'capture.json'
    source.write_text(json.dumps(dict(events=[
        dict(before_ns=1_000_000, group=0, pressed=1),
    ])))
    before = dict(pc_ns=0, offset_ns=0, uncertainty_ns=1)
    report = dict(
        exact_ordered_match=True, config={}, before_clock=before,
        after_clock=dict(before, pc_ns=100_000_000),
        counts=dict(midi_callback_calls=1, midi_events_processed_total=1,
                    rtp_send_calls=0),
    )
    capture.write_text(json.dumps(dict(report=report, arrivals_ns=[2_000_000])))
    script = Path(__file__).resolve().parents[1] / 'scripts/analyze_midi_latency.py'
    result = subprocess.run([sys.executable, str(script), str(source), str(capture)],
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert 'counters' in result.stderr
