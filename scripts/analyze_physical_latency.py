#!/usr/bin/env python3
"""Analyze externally captured sensor edges; this script does not acquire GPIO."""

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.physical_latency_analysis import analyze_capture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path, help="CSV: event_id,clock_id,trigger_ns,response_ns")
    parser.add_argument("--expected-events", type=int, required=True)
    parser.add_argument("--stimulus", choices=("key-contact", "midi-input"), required=True)
    parser.add_argument("--response", choices=("photodiode", "audio"), required=True)
    args = parser.parse_args()
    try:
        with args.capture.open(newline="", encoding="utf-8-sig") as source:
            result = analyze_capture(list(csv.DictReader(source)), args.expected_events)
    except (OSError, ValueError) as error:
        parser.exit(2, f"Invalid capture: {error}\n")
    result.update(stimulus=args.stimulus, response=args.response,
                  scope="External capture; physical sensor validity and edge pairing require operator verification")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
