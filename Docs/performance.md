# Performance and measurements

The figures below describe dated tests, not a guarantee for every Pi or network.
Physical key-to-light or key-to-sound latency has not been measured. Do not add
percentiles measured across different boundaries.

Historical MIDI benchmark runs used a source thread in the application process.
That source could slow down during stalls, reducing offered load. Those results
describe the emitted stream and cannot bound latency for independently arriving
MIDI. The current benchmark uses a separate source process and planned emission
times; use the same harness and configuration for new comparisons.

The [Pi acquisition in record 8bb30e7](measurements/pipeline_8bb30e7.md) covers
`bfbf93d`, including the changes in `656ec43`, with five interleaved runs per
bulk/fade setting, separate observer controls and isolated notes. The
[measurement index](measurements/README.md) records version coverage and chart
provenance. Earlier reports and the October Wi-Fi chart remain dated results.

The [current network acquisition at d119af1](measurements/rtp_latency_d119af1.md)
adds three pairs of production RTP/OSCMidi and direct UDP captures. All three
RTP captures fail delivery validation; the one exact UDP capture reaches
55.803 ms with ±2.766 ms clock-anchor uncertainty. These are actual-emission
network timings, distinct from the planned-emission MIDI benchmark above.

## Which boundary is measured?

| Measurement | Includes | Excludes |
| --- | --- | --- |
| Reception → processing | Queuing and processing within the visualizer | Time before the callback, network, instrument response |
| Synthetic source → instrumented output | Virtual ALSA input and MIDI pipeline | Keyboard and electrical USB link, remote network reception |
| Queued frame → completed transmission | Rendering wait and driver transmission | Light output measured by a sensor |
| Software publishing / simulated WebSocket | Queues, worker wake-up and simulated client call | Real WebSocket transport, network and GPIO |
| Pi ALSA → PC OSC | Visualizer, rtpmidid, network and RTP → OSC bridge | Keyboard, electrical USB link, audio/ASIO/VST rendering |

## MIDI pipeline and network results

- [Pi → RTP → OSCMidi and direct UDP — record d119af1](measurements/rtp_latency_d119af1.md):
  fresh delivery checks, rejected duplicate/incomplete sequences and a validated
  UDP timing series; [JSON](measurements/rtp_latency_d119af1.json),
  [capture archive](measurements/rtp_latency_d119af1_captures.json.gz) and
  [chart](assets/rtp_latency_d119af1.png).
- [LED bulk upload and fade cadence — record 8bb30e7](measurements/pipeline_8bb30e7.md):
  controlled A/B measurements at `bfbf93d`, including CPU and stall evidence;
  [JSON data](measurements/pipeline_8bb30e7.json),
  [compressed stall records](measurements/pipeline_8bb30e7_stalls.json.gz) and
  [chart](assets/pipeline_8bb30e7.png).
- [MIDI pipeline and LED rendering — record eccf25b](measurements/pipeline_eccf25b.md):
  before/after comparison, a 390,052-event test, memory usage and DMA transmission
  on the Pi; [JSON data](measurements/pipeline_eccf25b.json).
- [MIDI pipeline — record 9aa05ea](measurements/midi_pipeline_9aa05ea.md):
  a 52,052-event protocol, latencies, message order and hashes.
- [RTP delivery and QoS — record 9aa05ea](measurements/rtp_delivery_9aa05ea.md):
  controlled comparisons of network marking and long delivery tests.
- [Wi-Fi latency and jitter — record 9aa05ea](measurements/rtp_latency_9aa05ea.md):
  medians, p95/p99, spikes and clock synchronization uncertainty. The
  [JSON data](measurements/rtp_latency_9aa05ea.json) and
  [chart](assets/rtp_latency_9aa05ea.png) are retained.

In the October 18 local MIDI test, synthetic source → instrumented output
averages 7.5080 ms with a p99 of 13.2153 ms at 20 ms per chord. The historical
October long Wi-Fi test delivers 6,250/6,250 messages in order but reaches 97.34 ms. A shorter
lossless test therefore does not prove bounded latency.

## LED transmission — September 23, 2026

Test with virtual ALSA input, real GPIO/DMA rendering and simulated MIDI output,
using `scripts/benchmark_pipeline.py`. The workload includes pedal events,
fading notes and fast chords.

| Measurement | Result |
| --- | ---: |
| Events sent / received / processed | 52,052 / 52,052 / 52,052 |
| Remaining notes / sustain states | 0 / 0 |
| Black buffer after shutdown | yes |
| RSS after warm-up | 48,123,904 bytes, stable across samples |
| MIDI reception → processing, mean / maximum | 6.56 / 13.89 ms |
| LED transmission, mean / maximum | 10.42 / 18.46 ms |
| Queued frame → completed transmission, mean / maximum | 14.08 / 24.71 ms |

These timings are not photometric measurements. For 195 RGB LEDs at 800 kHz,
serial transmission alone takes 5.85 ms; this wiring cannot guarantee a complete
display update in under 5 ms. The observed RSS stability does not demonstrate
memory stability over several days.

## Software publishing — November 13, 2026

Pi Zero 2 W Rev 1.0, armv7l, Raspberry Pi OS Bookworm 12,
kernel `6.12.109+rpt-rpi-v7`, Python 3.11.2, revision `9f40b05`.
Three independent processes run `tools/latency_bench.py --json`, with
120 messages per scenario, while the production service remains active.
All messages are published and delivered in every test.

| Measurement | Mean, range across 3 tests | p95, range | Maximum, range |
| --- | ---: | ---: | ---: |
| MIDI admission → simulated WebSocket queue | 0.218–0.282 ms | 0.265–0.685 ms | 0.371–0.894 ms |
| `WakeableDeque.append` → simulated async `send` | 1.311–1.327 ms | 0.887–0.976 ms | 72.081–72.607 ms |
| Same publishing path with 10 ms polling | 5.679–5.843 ms | 10.501–10.579 ms | 10.592–10.777 ms |

Asynchronous port switching blocks the caller for 12.048–12.430 ms, compared with
161.340–161.401 ms for a simulated synchronous 150 ms notice. Shutdown during a
simulated 400 ms notice blocks for 0.454–0.464 ms.

A separate control associates a 74.167 ms WebSocket spike with a 72.919 ms
Python generation 2 collection. In another process, with GC disabled only after
the publishing scenario, the maximum is 1.089 ms and the p95 is 0.903 ms. This
control supports attributing the spike to the benchmark's GC; it does not
validate disabling GC in production. After the three tests: 45.084 °C,
`throttled=0x0`, load 0.35 / 0.31 / 0.26.

The [JSON results](measurements/software_latency_9aa05ea.json) contain the
three tests and the GC control. This benchmark opens neither GPIO outputs nor
hardware MIDI ports and does not measure real WebSocket or RTP transport.

## Reproducing the measurements

From the repository root, the software benchmark runs without hardware:

```bash
python3 tools/latency_bench.py --json
```

The full benchmark opens real GPIO/DMA resources and requires the service to
be stopped. On the Pi, during a maintenance window:

```bash
cd /home/Piano-LED-Visualizer
sudo bash <<'SH'
set -e
trap 'systemctl start visualizer.service' EXIT
systemctl stop visualizer.service
runner=/home/Piano-LED-Visualizer/.venv/bin/python
if [ ! -x "$runner" ]; then
    runner=/usr/bin/python3
fi
nice -n -10 "$runner" scripts/benchmark_pipeline.py
SH
```

The benchmark uses an instrumented MIDI output to avoid playing the piano.
Test settings remain in memory. RGB and sustain checks run before measurement;
warm-up events are excluded from measured counts. The default 2,000-chord run
therefore measures 52,000 events, compared with 52,052 in the historical protocol.
Web and platform/LCD mode are enabled by default. Their threads run, but the
benchmark does not generate browser or WebSocket client traffic.

The source opens its own ALSA output in a separate process on another allowed
CPU. The runtime pins itself automatically on the Pi Zero 2 W. On other boards,
select a runtime CPU with `PLV_MIDI_CPU_AFFINITY`. Launch with at least one more
allowed CPU so the source can run outside the runtime's affinity; the benchmark
fails explicitly when none is available. Both processes inherit the launch
priority and report their actual affinity and nice values. `nice -n -10` matches
the service's nice setting, but does not reproduce every systemd property.
The default source CPU is the first spare allowed CPU, which can be CPU 0.
Source scheduling jitter is included in the reported latency; IRQ activity on
that CPU can therefore affect the result. Try `PLV_BENCHMARK_SOURCE_CPU=1` if
CPU 1 is allowed and outside the runtime affinity, and keep it fixed across runs.

The source follows absolute deadlines and retains overdue events. Reported
latency starts at the intended emission time and includes source scheduling
lateness, which is also reported separately. Counts and hashes are checked
against actual source emissions as well as reception, processing and forwarding.
A missing final event fails validation even when every received event was handled.

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `PLV_BENCHMARK_WORKLOAD` | `chords` | Choose `chords`, `poisson` or `isolated`. |
| `PLV_BENCHMARK_CHORDS` | `2000` | Number of 12-note chords with pedal events; 26 events per chord. |
| `PLV_BENCHMARK_INTERVAL_MS` | `20` | Absolute target period between chords. |
| `PLV_BENCHMARK_RATE` | `100` | Individual events/s for the Poisson profile. |
| `PLV_BENCHMARK_DURATION` | `30` | Duration in seconds for Poisson or isolated notes. |
| `PLV_BENCHMARK_SEED` | `1` | Reproducible Poisson schedule, with at most ten simultaneous notes. |
| `PLV_BENCHMARK_SOURCE_CPU` | spare allowed CPU | Override source affinity; must be outside the runtime's affinity. |
| `PLV_BENCHMARK_WEB` | `true` | Set `false` for a controlled comparison without the web interface. |
| `PLV_BENCHMARK_APPMODE` | `platform` | Set `app` to exclude platform/LCD work. |
| `PLV_BENCHMARK_STALLS` | `1` | Set `0` to measure without the GC/canary monitor. |
| `PLV_BENCHMARK_PROFILE` | unset | cProfile output file; profiling changes the measured workload. |

For realistic load, repeat Poisson runs at 25, 100 and 300 events/s. Inside the
maintenance window above, replace the benchmark command with, for example:

```bash
PLV_BENCHMARK_WORKLOAD=poisson PLV_BENCHMARK_RATE=100 PLV_BENCHMARK_DURATION=60 nice -n -10 "$runner" scripts/benchmark_pipeline.py
```

Use `isolated` to measure a note after more than one second of silence following
release. Read `source_to_receive_by_type.note_on` and
`source_to_forward_by_type.note_on` for cold notes; releases have separate
statistics. Keep instrumentation, seed, priority, thermal conditions and other
load constant across comparisons. Do not directly compare profiled and
unprofiled runs. Compare with the canary disabled too, to quantify observer cost.
The canary requests a 1 ms interval (up to about 1,000 wakeups/s) in the
application process and shares its GIL and CPU affinity; stalls delay its actual
cadence. Keep `PLV_BENCHMARK_STALLS` fixed within each comparison;
repeat the comparison with `0` separately. For `isolated`, use
`PLV_BENCHMARK_DURATION=300` for roughly 200 cold `note_on` samples; the default
30 seconds supplies only about twenty.

### Comparing bulk upload and fade cadence

Run all four configurations with the current harness. The historical November
14 results cannot isolate these changes: the source process, web/LCD activity,
priority, canary and measured event count differ. Keep workload, source CPU,
seed, instrumentation and priority fixed. During the maintenance window above,
replace the single benchmark invocation with this interleaved comparison:

```bash
mkdir -p runs
for run in 1 2 3 4 5; do
  for cfg in "0 0" "1 0" "0 8" "1 8"; do  # BULK FADE_MS
    set -- $cfg
    PLV_LED_BULK_UPLOAD=$1 PLV_FADE_INTERVAL_MS=$2 nice -n -10 "$runner" \
      scripts/benchmark_pipeline.py > "runs/b${1}_f${2}_${run}.log" 2>&1
    grep '^BENCHMARK_JSON=' "runs/b${1}_f${2}_${run}.log" \
      > "runs/b${1}_f${2}_${run}.json"
  done
done
```

The `.json` files retain the `BENCHMARK_JSON=` prefix; remove it before JSON
parsing. Full logs retain benchmark failures, and `set -e` in the maintenance
shell stops on a failed run. Interleaving reduces thermal drift bias; also
record temperature and throttling, and vary configuration order between sets.
Use separate output directories for different workloads or monitor settings.

Compare `source_to_forward` (p50, p95, p99 and maximum),
`source_to_receive_by_type.note_on`, mean `led_pixel_upload`,
`process_fade_effects` and `main_loop`, and CPU samples. Check `stalls.gc` and
`stalls.stalls` around outliers. An upload time or CPU reduction is a hypothesis
until measured on the Pi; x86 timings and estimates do not establish a
production gain.

### Rendering and diagnostics

Supported initialized WS281x channels use a bulk copy of native 32-bit pixel
words. Other bindings retain the public per-pixel setters. The driver continues
to handle color order, gamma and brightness, and one worker serializes render,
DMA completion and shutdown blackout. Set `PLV_LED_BULK_UPLOAD=0` to compare
against the setter path; the report records which path was selected.

Pure `Fading` work targets an 8 ms period when no MIDI was processed. Incoming
MIDI interrupts the wait, pending MIDI skips sleeping, and fade decay uses elapsed
time. `PLV_FADE_INTERVAL_MS=0` restores the existing state-based wait for a
comparison. Other effect modes retain their existing cadence. In the
[chord tests in record 8bb30e7](measurements/pipeline_8bb30e7.md), bulk upload at
fade 0 lowers the median mean upload time from 0.908 to 0.253 ms/frame (3.6×),
while process CPU changes from about 97.5% to 96.4% of one core. The expected
large CPU and loop-count reductions are not demonstrated; no optical latency
result has been measured.

LED diagnostics separate `led_pickup_delay`, `led_pixel_upload`, `led_render`
and `led_dma_wait`, alongside the existing transmission totals. `led_render`
measures the backend `show()` call, including any synchronous SPI work; it is
not an electrical measurement of DMA startup or light. Do not infer a
position-dependent optical correction from serial bit arrival: the strip also
has frame-latching/reset behavior and its own PWM timing.

The optional benchmark stall monitor records GC generation, start/end time and
duration, plus canary wakeups more than 5 ms late on a nominal 1 ms interval.
It retains at most 1,024 records of each kind and total occurrence counts.
The canary samples cumulative main/canary thread
`/proc/self/task/<tid>/schedstat` counters at startup, then every 50 ms (on its
next wakeup), and at each stall. Each stall retains the current counters and
`schedstat_previous`, including the previous sample's `observed` timestamp.
Subtract the previous counters from the current ones to examine changes over
that interval. The interval can include activity before the stall, and sampling
itself can be delayed; it does not identify an exact preemption duration.
An increase in `run_delay_ns` supports runnable scheduling delay; blocked GIL
time need not accrue run delay. Missing counters remain `null`. A GC overlap
is evidence to examine, not an automatic attribution. This monitor is attached
only by the benchmark; production stalls are not collected by it.

All monitor timestamps use `perf_counter`, as does the runtime timing field
`max_recorded_at_perf`. That field dates the recording of a new maximum after
the measured operation; it provides approximate correlation rather than a
hardware timestamp. The clock is read only for new maxima. Aggregate historical
maxima without timestamps cannot establish simultaneous stalls or their cause.

Analyzing a network capture with `scripts/analyze_midi_latency.py` requires
source and receiver timestamps and validation of message identity and order.
Published JSON files are summaries; they do not replace these raw captures.
See the [network protocol](measurements/rtp_latency_9aa05ea.md#measurement).

## Preparing a physical measurement

Physical measurement requires a sensor; none is connected to the hardware used
for the tests above. Software timings or DMA completion must not be presented
as key-to-light or key-to-sound latency.

Use a single capture device for both the trigger and response: a key contact
or MIDI input for the trigger, and a photodiode or audio signal for the response.
Using MIDI input as the trigger excludes keyboard scanning time. Establish the
detection threshold, sampling rate and edge pairing before calculating
percentiles.

The CSV export must contain the following columns, with timestamps in
nanoseconds on that same clock and consecutive event IDs from zero to one less
than the expected event count:

```csv
event_id,clock_id,trigger_ns,response_ns
```

```bash
python3 scripts/analyze_physical_latency.py capture.csv --expected-events 100 --stimulus midi-input --response photodiode
```

Set the expected count to match the protocol actually sent. Choose `key-contact`
for a key contact and `audio` for an audio response. The tool rejects incomplete
or out-of-order captures, multiple clock IDs and invalid timestamps. It
calculates the mean, median, p95, p99 and maximum without silent realignment.
It does not certify the sensor or edge pairing.

For a longer MIDI test, increase `PLV_BENCHMARK_CHORDS`. The report retains RSS
and CPU samples with elapsed time. Counters and hashes cover the entire
sequence; probe latencies cover at most the latest 100,000 events. These timings
exclude cleanup messages sent after the final snapshot. The reconnection
monitor is disabled during benchmark preparation without changing the saved
RTP peer.
