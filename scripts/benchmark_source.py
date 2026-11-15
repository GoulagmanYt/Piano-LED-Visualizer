#!/usr/bin/env python3
"""Independent ALSA source. stdout is a ready line, then one JSON report."""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.benchmark_workload import transmit, workload


def main():
    import mido

    config = json.loads(sys.stdin.readline())
    if config['cpu'] is not None:
        os.sched_setaffinity(0, {config['cpu']})
    with mido.open_output(config['port']) as output:
        print('READY', flush=True)
        epoch = float(sys.stdin.readline())
        report = transmit(workload(**config['workload']),
                          lambda data: output.send(mido.Message.from_bytes(data)),
                          epoch, clock=time.perf_counter, sleep=time.sleep)
    report['cpu_affinity'] = sorted(os.sched_getaffinity(0))
    report['nice'] = os.getpriority(os.PRIO_PROCESS, 0)
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
