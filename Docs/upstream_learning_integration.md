# Synthesia Learning bridge: implementation and validation

The fork's existing input, playback and RTP routing remains the default. The
opt-in bridge is configured separately in Ports Settings; changes take effect
on restart. The bridge uses two explicit MIDI inputs and two outputs, so it
can distinguish a piano performance from a computer guide stream. The LCD
menu does not configure the bridge or switch its mode.

`LearningSession` serializes routing and only enqueues output. Independent
`LearningOutput` workers own each output and drain cleanup before closing it;
a failed worker rejects new messages and tries to silence the port. The bridge
stops and reopens only after its old workers finish. Source-aware guide events
have a separate render queue; local song playback/practice take over the LEDs
and stale guides are discarded. New installs no longer create the legacy udev
mesh script or MIDI service. Existing installs retain their in-app connection
manager; the bridge disables its automatic `connectall` path while active.

The bridge refuses to start when `aconnect -l` cannot be inspected, when
endpoints are missing or ambiguous, or when it detects a direct ALSA
piano-to-computer/computer-to-piano connection. It does not remove connections
or detect routing loops outside the Pi. Remove those manually. Computer control
and program changes are blocked by default. On shutdown and port changes the
bridge queues sustain-off and note-off messages for notes it forwarded.

## Validation still required on hardware

The Python tests simulate ALSA graphs, ports, workers, disconnects, routing,
recording and LED rendering; they do not prove behavior on real hardware. Before
using the bridge for a performance, test on the target Raspberry Pi with a USB
piano and the chosen RTP/USB computer connection: Wait and Watch/Listen,
partial chords, finger channels 1–12, simultaneous same-pitch notes, output
errors, hot-unplug/reconnect, and sustained notes during shutdown. Check for
external MIDI feedback loops, measure latency and verify audio/LED behavior.
Do not rely on software note-off cleanup as the only way to stop a piano if a
cable or device fails. Avoid running local song playback concurrently with an
external Synthesia session, since both may send notes to the piano.
