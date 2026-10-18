# MIDI latency debugging implementation plan

**Goal:** identify and repair Pi MIDI loss/latency, push tested fixes, deploy using the web update button, and verify on hardware.

**Architecture:** retain FIFO deques and the serialized forwarding/session policy. Remove unnecessary shared locking from independent deque consumers; never hold the queue lock while waking the render thread. Use exact event sequences and bounded waits in hardware stress tests.

**Tech stack:** Python, pytest, mido/python-rtmidi, Linux ALSA, WS281x, Playwright.

**Acceptance:** sent, received, processed and forwarded sequences match; no stuck notes/pedal; queues drain; no ALSA allocation failures; compare unprofiled timings under the same load. Software measurements do not establish physical USB or key-to-light latency, or guarantee delivery across arbitrary network outages.

1. Reproduce lock contention with blocked callback notification and independent consumers (`tests/test_midi_pipeline_concurrency.py`). Run failing tests before changing `lib/midi_queues.py`. Keep producer/session mutations protected and make deque drains tolerate concurrent clears.
2. Measure send-queue residence separately from native send duration in `lib/midiports.py`, with a regression test. Count callback arrivals so HTTP diagnostics can distinguish ingress and processing.
3. Strengthen `scripts/benchmark_pipeline.py`: exact ordering/fingerprints at input and null output, forwarding count, bounded drain, latency percentiles. Reproduce a dropped/reordered output in a test before implementation.
4. Run the complete pytest suite and compare the production renderer on the Pi before/after, using bounded remote execution with automatic service restart. Record counts, timings, ALSA counters, thermal state and limitations in the audit report.
   The Zero 2 W trials isolate a second bottleneck: multicore Python GIL handoffs. Apply measured, model-specific startup affinity (`lib/midi_runtime_tuning.py`), with allowed-CPU checks, an off switch and nonfatal OS errors, and regression tests in `tests/test_midi_runtime_tuning.py`.
5. Review the diff, commit only task files, push origin/master, click the actual web update button, and check update status/revision, service, MIDI ports and hardware stress results.

Baseline: 221 tests and 6 subtests pass. Pi 52,052 events received and processed, 0 state left; receive-to-process 43.75 ms average / 339.69 ms maximum. Forward queue sampled age reached 8.60 seconds. Thread sampling shows shared queue-lock waits in callback, renderer, forwarder and web publisher; profiling adds overhead and is excluded from before/after acceptance measurements.
