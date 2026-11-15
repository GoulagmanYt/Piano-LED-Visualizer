# Measurement records and version coverage

## Current measured runtime: bfbf93d

The [November 15 Pi acquisition](pipeline_2026-11-15.md) measures runtime
`bfbf93d`, including `656ec43` (bulk LED upload, fade cadence and the revised
benchmark) and the periodic scheduler-sampling correction. It includes five
interleaved repetitions of all four bulk/fade settings, separate observer
controls and a current-version isolated-note run. The [new chart](../assets/pipeline_2026-11-15.png)
comes from those measurements. x86 timings and earlier estimates are not used
as Pi results.

| Record | Measured version or scope | Coverage of the current update |
| --- | --- | --- |
| [Pipeline A/B, November 15](pipeline_2026-11-15.md), [JSON](pipeline_2026-11-15.json), [stall archive](pipeline_2026-11-15_stalls.json.gz), [chart](../assets/pipeline_2026-11-15.png) | `bfbf93d`; independent source on CPU 1, runtime on CPU 2; real GPIO/DMA | Measures bulk/fade settings with the revised harness; latest pipeline acquisition |
| [Pipeline and LED rendering, November 14](pipeline_2026-11-14.md), [JSON](pipeline_2026-11-14.json) | `9aa05ea` versus `5d2972f`; Pi Zero 2 W; earlier benchmark | Neither update measured; latest published full-pipeline Pi acquisition |
| [Software latency, November 13 JSON](software_latency_2026-11-13.json) | `9f40b05`; software mocks on Pi; three independent processes | No GPIO, real network or measurements of these updates; [interpretation](../performance.md#software-publishing--november-13-2026) |
| [MIDI pipeline, October 18](midi_pipeline_2026-10-18.md) | Earlier pipeline and benchmark; multiple configurations | Historical results; no commit revision retained in this report |
| [RTP delivery, October 18](rtp_delivery_2026-10-18.md) | Controlled network marking and delivery tests | Historical network observations; not repeated for these updates |
| [Wi-Fi latency, October 18](rtp_latency_2026-10-18.md), [JSON](rtp_latency_2026-10-18.json), [chart](../assets/rtp_latency_2026-10-18.png) | Earlier Pi-to-PC and raw UDP captures; no application revision retained | Historical estimated network latency; not a bulk-upload or fade comparison |

The JSON files retain their original acquisition dates, revisions, conditions
and values. Documentation updates do not turn them into fresh acquisitions.
None of these records measures physical key-to-light or key-to-sound latency.

## Chart provenance

The [November 15 pipeline chart](../assets/pipeline_2026-11-15.png) uses the
twenty `matrix` runs in the new JSON. Dots show individual runs and bars show
the median of run statistics. It measures software timing and CPU under the
recorded chord workload; the isolated-note and monitor-disabled runs are
reported separately. The [plotting tool](../../tools/plot_pipeline_measurements.py)
validates the dataset before rendering.

The [existing Wi-Fi chart](../assets/rtp_latency_2026-10-18.png) uses the two
`plot_series` in [the October 18 JSON](rtp_latency_2026-10-18.json):

- `baseline-usb-return`: 1,880 full-path messages after USB reconnection.
- `raw-unique-traffic`: 1,880 messages in the raw UDP network control.

Both panels use these same observations: estimated latency over elapsed time,
then over the Pi clock phase modulo four seconds. The panels do not compare
software versions. The plot precedes the router channel tests and does not
show the final 6,250-message run. Absolute latency has the clock uncertainty
described in the [measurement protocol](rtp_latency_2026-10-18.md#measurement).

## Publishing results for the update

Use the [current A/B protocol](../performance.md#comparing-bulk-upload-and-fade-cadence)
on the Pi, with all four bulk/fade settings interleaved in the same harness.
Keep the source CPU, workload, priority and instrumentation fixed. Run the
canary-disabled comparison separately. The historical November 14 benchmark
used an in-process source and a different event count; its latencies are not
a baseline for the revised independent-source benchmark.

For each new acquisition, retain the exact tested revision, benchmark/probe
source identity, environment settings, hardware/kernel/Python versions, actual
CPU affinity and nice values, temperature/throttling, complete benchmark reports
and logs. Validate counts, hashes, queue drain and shutdown state before
publishing latency statistics. Record bulk-upload path selection and the
monitor setting so runs with different observer costs remain distinguishable.

Create a separately dated report and dataset for the new acquisition. Generate
any new chart from that dataset, label the measured boundary, units, sample
counts and configurations, and link its source data. Keep the historical files
as dated evidence. Use the November 15 results for configuration-specific
observations about A and B; they do not establish results under other workloads
or physical latency gains. Production stalls remain outside the benchmark
monitor's collection scope.
