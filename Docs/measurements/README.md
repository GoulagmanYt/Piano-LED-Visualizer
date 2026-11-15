# Measurement records and version coverage

## Latest records: network d119af1; pipeline 8bb30e7

The [fresh RTP/UDP acquisition](rtp_latency_d119af1.md) tests runtime `d119af1`.
Three full RTP captures fail delivery validation. One exact direct-UDP capture
reaches 55.803 ms, with ±2.766 ms clock-anchor uncertainty; two other UDP runs
contain duplicates. The [current network chart](../assets/rtp_latency_d119af1.png)
shows delivery outcomes and only the strictly validated latency series.
The older `9aa05ea` network chart is historical and has not been relabelled as
a current capture.

The [Pi acquisition in record 8bb30e7](pipeline_8bb30e7.md) measures runtime
`bfbf93d`, including `656ec43` (bulk LED upload, fade cadence and the revised
benchmark) and the periodic scheduler-sampling correction. It includes five
interleaved repetitions of all four bulk/fade settings, separate observer
controls and a current-version isolated-note run. The [new chart](../assets/pipeline_8bb30e7.png)
comes from those measurements. x86 timings and earlier estimates are not used
as Pi results.

## File naming and provenance

Names use a commit version instead of a date: `<measurement>_<commit>.<format>`.
The suffix identifies the published record snapshot; `record_revision` stores
that commit in JSON. The actual tested runtime remains in `revision` or
`runtime_revision`, or in
`baseline_revision` and `candidate_revision` for historical comparisons.
Acquisition dates remain inside the reports and metadata.

The latest network record tests `d119af1`, the HEAD selected for its acquisition.
The LED A/B record uses publication version `8bb30e7`.
Its runtime and benchmark sources are identical to measured revision `bfbf93d`;
the commit only publishes documentation, data and the plotting tool. Historical
records use publication snapshots `eccf25b` and `9aa05ea`. In particular, the
network files' `9aa05ea` suffix does not establish an unknown tested application
revision. Renaming a record does not create a new acquisition.

| Record | Measured version or scope | Coverage of the current update |
| --- | --- | --- |
| [RTP/UDP, record d119af1](rtp_latency_d119af1.md), [JSON](rtp_latency_d119af1.json), [captures](rtp_latency_d119af1_captures.json.gz), [chart](../assets/rtp_latency_d119af1.png) | Runtime `d119af1`; production RTP/OSCMidi and direct UDP; three interleaved pairs | Current network evidence: RTP delivery failures and a validated UDP delay spike |
| [Pipeline A/B, record 8bb30e7](pipeline_8bb30e7.md), [JSON](pipeline_8bb30e7.json), [stall archive](pipeline_8bb30e7_stalls.json.gz), [chart](../assets/pipeline_8bb30e7.png) | `bfbf93d`; independent source on CPU 1, runtime on CPU 2; real GPIO/DMA | Measures bulk/fade settings with the revised harness; latest pipeline acquisition |
| [Pipeline and LED rendering, record eccf25b](pipeline_eccf25b.md), [JSON](pipeline_eccf25b.json) | `9aa05ea` versus `5d2972f`; Pi Zero 2 W; earlier benchmark | Historical full-pipeline acquisition; predates both updates |
| [Software latency, record 9aa05ea JSON](software_latency_9aa05ea.json) | `9f40b05`; software mocks on Pi; three independent processes | No GPIO, real network or measurements of these updates; [interpretation](../performance.md#software-publishing--november-13-2026) |
| [MIDI pipeline, record 9aa05ea](midi_pipeline_9aa05ea.md) | Earlier pipeline and benchmark; multiple configurations | Historical results; no tested commit revision retained in this report |
| [RTP delivery, record 9aa05ea](rtp_delivery_9aa05ea.md) | Controlled network marking and delivery tests | Historical network observations; not repeated for these updates |
| [Wi-Fi latency, record 9aa05ea](rtp_latency_9aa05ea.md), [JSON](rtp_latency_9aa05ea.json), [chart](../assets/rtp_latency_9aa05ea.png) | Earlier Pi-to-PC and raw UDP captures; no application revision retained | Historical reference; current capture is record d119af1 |

The JSON files retain their original acquisition dates, revisions, conditions
and values. Documentation updates do not turn them into fresh acquisitions.
None of these records measures physical key-to-light or key-to-sound latency.

## Chart provenance

The [record d119af1 network chart](../assets/rtp_latency_d119af1.png) shows all
six delivery results. Only `raw-3` passes strict identity/order/count validation
and appears in the timing panels. The [network plotting tool](../../tools/plot_rtp_measurements.py)
reconstructs payloads and recomputes statistics from the published capture
archive; it never deduplicates or realigns a failed capture.

The [record 8bb30e7 pipeline chart](../assets/pipeline_8bb30e7.png) uses the
twenty `matrix` runs in the new JSON. Dots show individual runs and bars show
the median of run statistics. It measures software timing and CPU under the
recorded chord workload; the isolated-note and monitor-disabled runs are
reported separately. The [plotting tool](../../tools/plot_pipeline_measurements.py)
validates the dataset before rendering.

The [historical Wi-Fi chart](../assets/rtp_latency_9aa05ea.png) uses the two
`plot_series` in [record 9aa05ea JSON](rtp_latency_9aa05ea.json):

- `baseline-usb-return`: 1,880 full-path messages after USB reconnection.
- `raw-unique-traffic`: 1,880 messages in the raw UDP network control.

Both panels use these same observations: estimated latency over elapsed time,
then over the Pi clock phase modulo four seconds. The panels do not compare
software versions. The plot precedes the router channel tests and does not
show the final 6,250-message run. Absolute latency has the clock uncertainty
described in the [measurement protocol](rtp_latency_9aa05ea.md#measurement).

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

Create a separate report and dataset named for the selected commit version.
Keep the acquisition date and tested revision in their metadata. Generate
any new chart from that dataset, label the measured boundary, units, sample
counts and configurations, and link its source data. Keep the historical files
as historical evidence. Use record 8bb30e7 for configuration-specific
observations about A and B; they do not establish results under other workloads
or physical latency gains. Production stalls remain outside the benchmark
monitor's collection scope.

## Published data and privacy

Published reports, JSON and compressed archives exclude credentials, personal
hostnames, IP/MAC addresses, home-directory paths and MIDI port identities.
Raw logs and connection settings remain private. Review archive contents as
well as visible documents before publication; retain timing, count, hash and
hardware-version evidence needed to interpret the measurements.
