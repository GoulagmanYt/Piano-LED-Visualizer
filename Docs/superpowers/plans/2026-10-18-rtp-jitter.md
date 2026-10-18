# RTP Wi-Fi latency and jitter implementation plan

> Execute tasks sequentially, with measured comparisons before retaining changes.

**Goal:** Reduce Pi → OSCMidi message latency and rare delayed notes over the existing Wi-Fi connection, without increasing drops or changing message order.

**Architecture:** Timestamp a known MIDI sequence at injection into the production ALSA input and on OSCMidi's existing local OSC output. Bound the Pi/PC monotonic clock offset with timestamped UDP exchanges before and after each run. Report absolute latency with clock uncertainty, interval error independent of offset, and chord dispersion. Use direct UDP and synthetic RTP controls to isolate the network and receiver when needed.

**Tech stack:** Python standard library on Windows, Python/Mido on Pi, existing visualizer and OSCMidi, SSH, Linux networking and systemd tools.

**Spec:** User request in this session: optimize Wi-Fi latency, message spacing and exceptional late notes, while minimizing loss.

## Constraints

- Keep the previously proven harmful DSCP EF / priority 6 overrides disabled.
- Do not claim synchronized-clock precision without an uncertainty bound.
- Reject delivery/order mismatches as benchmark failures; do not silently compute misleading latency percentiles on shifted message indices.
- Preserve the user's OSCMidi routing, plugin and audio configuration unless a measured bottleneck justifies a reversible change.
- Capture original OS settings and restore losing candidates. Retain only improvements supported by comparable runs.

## Tasks

1. Build a maintenance measurement probe with source and arrival timestamps, clock calibration, exact sequence checks, latency percentiles, interval errors, late-event counts and chord spread. Check its arithmetic against known synthetic timestamps before trusting device measurements.
2. Establish repeated production baselines, including realistic notes/chords and sustained high load. Record Pi software counters, queues, Wi-Fi TX failures and OSCMidi diagnostics.
3. Isolate the dominant tail: compare controlled UDP/RTP paths and inspect actual RTP clock/scheduler waits. Test one applicable configuration at a time (network scanning, power/scheduling, RTP processing), with rollback on regression.
4. If code changes are necessary, add a failing regression for the measured defect, implement the minimal correction, and run relevant tests plus independent review before integration.
5. Repeat winning and original conditions, run a longer delivery/jitter check, persist validated settings, document limits and results, and push/deploy authorized project changes through the web updater.

## Acceptance

- Report median/p95/p99/max, exceptional delays and inter-message interval errors for baseline and final conditions.
- Exact expected delivery and order in final measured runs; queue drains and no allocator/audio drop regression.
- Explain which boundary improved and distinguish software/OSC arrival from physical keyboard-to-audio latency.
- Final services and connection healthy; temporary peers/probes closed; repository changes and device settings documented.

## Measured execution result

The measurements and isolation tests are recorded in
[the investigation report](../../rtp_latency_2026-10-18.md). No additional tuning
candidate demonstrated a repeatable gain; PC, firmware and router changes were
restored. The last restored 6,250-message run delivered exactly, but reached
97.34 ms; another long run lost two messages. The latency/loss objective remains
open beyond Pi host enqueue. A different Wi-Fi interface or access point is
needed for the next discriminating A/B/A test; neither was available. The code
change adds offline analysis and its regressions, without changing MIDI runtime
behavior or claiming the remaining network stalls are fixed.
