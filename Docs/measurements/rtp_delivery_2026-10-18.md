# RTP delivery and QoS marking — October 18, 2026

## Controlled comparison

The same service, MIDI ports, OSCMidi and 1 000 synthetic messages are used.
Only the Pi's `inet oscmidi_qos` nftables table changes. The PC receiver compares
the count, order and hash of OSC messages. The general firewall and audio
settings remain identical.

This table, created by `scripts/setup-pi-qos.sh` from another repository
(`RTP-OSC-Midi-tool`), forced DSCP EF and packet priority 6 on UDP ports 5004/5005
and the rtpmidid process. These are not drop rules, but they degrade delivery on
the Wi-Fi link tested with `brcmfmac` and kernel `6.12.109+rpt-rpi-v7`.

| Configuration | OSC messages / 1 000 expected | Wi-Fi `tx failed`, before → after |
| --- | ---: | --- |
| No forced QoS | 1 000, identical order and hash | 222 → 222 |
| Original DSCP and priority re-enabled | 980 | 222 → 240 |
| DSCP EF only | 986 | 240 → 254 |
| Priority 6 only | 966 | 254 → 282 |

An initial test before modification delivered 984/1 000. Re-enabling the
markings brings the losses back; removing only one family of rules is
insufficient in this installation. These results do not prescribe a universal
QoS policy for other networks.

## Long tests without these markings

| Path and load | Result |
| --- | --- |
| Production, burst of 10 000 messages | All received, processed, forwarded and observed in order on the PC, identical hash |
| Production, 52 000 chord and pedal messages | 52 000 at each Pi boundary, 51 990 OSC messages |
| Direct synthetic RTP source, 52 000 messages | 52 000 outgoing packets captured on the Pi, 51 970 OSC messages; `tx failed` 285 → 312 |
| RTP source, instrumented arrival at PC port 5005 then local relay | 52 000 packets and 52 000 OSC messages, identical order and hash |
| Final direct production test, 52 000 messages, chords at 5 ms | 52 000 at each boundary and on the PC, identical order and hash |

The final test's hash is
`54c063633795bc04ec6b5f58dc8ff490bce9ae4307474c12f3e117a6852fcd57`.
The queues drain and the ALSA pools have no allocation failures.

An RTP session unavailable during reconnection is excluded from comparisons
while connected. The usual OSCMidi ports are 5004/5005; relay tests temporarily
move the server, then restore its configuration.

## Interpretation and limits

The dedicated table's markings were removed on the tested Pi without changing
the other firewall tables. Running their generator script again could reinstall
them. The visualizer's stability script does not remove these external rules:
inspect them separately.

An AF_PACKET capture on `wlan0` sees packets before the outcome of their radio
transmission. The number of missing OSC messages is not inherently equal to the
failed Wi-Fi frame count. The controlled comparisons establish the effect of
the markings; they do not locate the radio or firmware mechanism responsible
for the remaining rare losses.

These tests establish neither an OSCMidi decoder defect nor lossless delivery
under all circumstances. They exclude the electrical USB path and physical
key → sound latency. The [long Wi-Fi measurements](rtp_latency_2026-10-18.md)
also show delay spikes despite a fully received sequence.
