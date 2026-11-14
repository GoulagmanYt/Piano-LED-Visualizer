# MIDI pipeline measurements — October 18, 2026

## Protocol

`scripts/benchmark_pipeline.py` uses a virtual ALSA input, the production MIDI
processor and GPIO/DMA renderer, and an instrumented output that does not play
the piano. The service is stopped for the test and then restarted. Test settings
remain in memory. The results below exclude cProfile.

The test includes pedal events, single notes and 2 000 twelve-note chords with
CC64: 52 052 events, approximately 1 300 events/s during the chords at 20 ms.
The 5 ms test increases the load. Counts and SHA-256 hashes are compared at the
emission, reception, processing and forwarding boundaries.

## Reception → processing

| Configuration | Events received / processed | Mean / maximum |
| --- | --- | ---: |
| Initial pipeline, original benchmark | 52 052 / 52 052 | 43.7468 / 339.6860 ms |
| Independent consumers, original benchmark | 52 052 / 52 052 | 17.8742 / 90.7361 ms |
| Exact tracing, four cores | 52 052 / 52 052 | 28.1242 / 192.5186 ms |
| Same tracing, CPU 2 affinity through taskset | 52 052 / 52 052 | 5.7381 / 28.3685 ms |
| Automatic affinity from the application | 52 052 / 52 052 | 5.7660 / 44.4138 ms |
| Native queue, chords at 20 ms | 52 052 / 52 052 | 4.5544 / 15.7426 ms |
| Native queue, chords at 5 ms | 52 052 / 52 052 | 9.5570 / 53.6672 ms |

Exact tracing computes hashes and adds work; rows with and without this tracing
do not use identical instrumentation.

## Synthetic source → instrumented output

| Configuration | Mean | p99 |
| --- | ---: | ---: |
| Automatic affinity, before native queue | 11.0674 ms | 22.5637 ms |
| Native queue, chords at 20 ms | 7.5080 ms | 13.2153 ms |
| Native queue, chords at 5 ms | 11.9746 ms | 31.7600 ms |

The mean output wait in the first scenario is 4.7111 ms. All three sequences
have identical hashes at the four boundaries:
`f6c2a1ecac76ebaf952b04ded439fa8546781829790914bb5c6b86e6b773ae05`.
The queues drain, no note or pedal remains active, and the LED buffer is black
after shutdown. Neither native-queue test has an ALSA allocation failure.

The LED buffer copy microbenchmark, using the same 195-LED buffers and 10 000
calls, drops from 124.29 to 18.98 µs per call with a slice copy.

## Network delivery checks

These tests precede the removal of the QoS markings described in the
[RTP delivery measurements](rtp_delivery_2026-10-18.md).

| Test | Observation |
| --- | --- |
| Production, 1 000 events, Pi output capture | 1 000 received, processed, sent and captured RTP packets |
| Same test, OSCMidi output on the PC | 976/1 000 OSC messages; subsequent tests 968 then 966 |
| Production, burst of 10 000 events | 10 000 forwarded by the Pi, 9 938 observed on the PC |
| Independent Pi → PC UDP, two sending modes | 1 000/1 000 in order for each mode |
| Direct synthetic Pi → OSCMidi RTP | 962/1 000 OSC messages |
| Local RTP loopback on the PC | 1 000/1 000, identical order and hash |
| RTP through a temporary relay on the PC, then local OSCMidi | 1 000 packets received and 1 000 OSC messages, identical hash |

An outgoing capture on the Pi does not prove radio delivery. These software
durations exclude the keyboard, physical USB transport and LED light; zero loss
in these sequences does not guarantee delivery during a disconnection or a
prolonged stall. The native queue remains finite.
