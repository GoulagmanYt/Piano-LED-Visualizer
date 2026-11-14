# Performance and measurements

The figures below describe dated tests, not a guarantee for every Pi or network.
Physical key-to-light or key-to-sound latency has not been measured. Do not add
percentiles measured across different boundaries.

## Which boundary is measured?

| Measurement | Includes | Excludes |
| --- | --- | --- |
| Reception → processing | Queuing and processing within the visualizer | Time before the callback, network, instrument response |
| Synthetic source → instrumented output | Virtual ALSA input and MIDI pipeline | Keyboard and electrical USB link, remote network reception |
| Queued frame → completed transmission | Rendering wait and driver transmission | Light output measured by a sensor |
| Software publishing / simulated WebSocket | Queues, worker wake-up and simulated client call | Real WebSocket transport, network and GPIO |
| Pi ALSA → PC OSC | Visualizer, rtpmidid, network and RTP → OSC bridge | Keyboard, electrical USB link, audio/ASIO/VST rendering |

## MIDI pipeline and network results

- [MIDI pipeline and LED rendering — November 14, 2026](measurements/pipeline_2026-11-14.md):
  before/after comparison, a 390,052-event test, memory usage and DMA transmission
  on the Pi; [JSON data](measurements/pipeline_2026-11-14.json).
- [MIDI pipeline — October 18, 2026](measurements/midi_pipeline_2026-10-18.md):
  a 52,052-event protocol, latencies, message order and hashes.
- [RTP delivery and QoS — October 18, 2026](measurements/rtp_delivery_2026-10-18.md):
  controlled comparisons of network marking and long delivery tests.
- [Wi-Fi latency and jitter — October 18, 2026](measurements/rtp_latency_2026-10-18.md):
  medians, p95/p99, spikes and clock synchronization uncertainty. The
  [JSON data](measurements/rtp_latency_2026-10-18.json) and
  [chart](assets/rtp_latency_2026-10-18.png) are retained.

In the October 18 local MIDI test, synthetic source → instrumented output
averages 7.5080 ms with a p99 of 13.2153 ms at 20 ms per chord. The final long
Wi-Fi test delivers 6,250/6,250 messages in order but reaches 97.34 ms. A shorter
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

The [JSON results](measurements/software_latency_2026-11-13.json) contain the
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
"$runner" scripts/benchmark_pipeline.py
SH
```

The benchmark uses an instrumented MIDI output to avoid playing the piano.
Test settings remain in memory. `PLV_BENCHMARK_CHORDS` and
`PLV_BENCHMARK_INTERVAL_MS` adjust the workload; `PLV_BENCHMARK_PROFILE` enables
cProfile. Do not directly compare latencies collected with and without
profiling.

Analyzing a network capture with `scripts/analyze_midi_latency.py` requires
source and receiver timestamps and validation of message identity and order.
Published JSON files are summaries; they do not replace these raw captures.
See the [network protocol](measurements/rtp_latency_2026-10-18.md#measurement).

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
