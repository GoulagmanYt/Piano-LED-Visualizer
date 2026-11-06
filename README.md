# Piano LED Visualizer

[![Raspberry Pi Zero 2 W](https://img.shields.io/badge/hardware-Raspberry%20Pi%20Zero%202%20W-C51A4A?logo=raspberrypi&logoColor=white)](https://www.raspberrypi.com/products/raspberry-pi-zero-2-w/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Light up piano keys as you play. Piano LED Visualizer runs on a Raspberry Pi and drives a WS2812B LED strip from USB or network MIDI. A web interface handles colors, MIDI ports, song playback and recordings. An optional LCD provides local controls.

This fork of [onlaj/Piano-LED-Visualizer](https://github.com/onlaj/Piano-LED-Visualizer) targets the Raspberry Pi Zero 2 W. Work here focuses on MIDI delivery, reconnecting devices, reducing idle CPU use and integrating with [OSC Midi Tool](https://github.com/GoulagmanYt/RTP-OSC-Midi-tool).

[Installation](#installation) · [MIDI setup](#midi-setup) · [Documentation](#documentation) · [Development](#development)

## Features

- LED colors based on note, velocity or playing speed, with fading, backlight and animation settings.
- MIDI file playback, recording and guided practice, including Synthesia integration.
- USB MIDI input with an Auto mode that keeps the current device connected and waits when no device is available.
- RTP-MIDI routing through rtpmidid, with peer selection and connection diagnostics in the web interface.
- Browser controls available in 12 languages, plus an optional Waveshare LCD menu.
- Updates with configuration backups, service health checks and rollback on failure.

The [feature guide](Docs/features.md) covers the color modes, song controls and animations.

## Hardware

| Component | Setup |
| --- | --- |
| Raspberry Pi | Zero 2 W, the target board for this fork |
| LED strip | WS2812B, typically 144 LEDs/m; roughly 1.5 to 2 m for an 88-key keyboard |
| Power | Regulated 5 V supply, sized for the LED count and brightness |
| Storage | 16 GB or larger microSD card with Raspberry Pi OS Lite |
| MIDI source | USB MIDI piano or a network MIDI connection |
| Display, optional | Waveshare 1.44-inch SPI LCD with navigation controls |

Power the LED strip from its own supply connection and share ground with the Pi. Do not draw the strip's current through the GPIO header. Both the Pi and the strip require 5 V; a 9 V or 12 V supply will damage them.

## Installation

Start with Raspberry Pi OS Lite. The [installation guide](Docs/manual_installation.md) covers OS setup, SPI, dependencies and the systemd service. For a headless setup, see the [Wi-Fi guide](Docs/wifi_setup.md).

The installer configures system packages, the hostname, the `plv` account and services. Review [autoinstall.sh](autoinstall.sh), then run it on the Pi:

```bash
curl -fsSLo autoinstall.sh https://raw.githubusercontent.com/GoulagmanYt/Piano-LED-Visualizer/master/autoinstall.sh
sudo bash autoinstall.sh
```

Once the service is running, open:

```text
http://pianoledvisualizer.local
```

If your network does not resolve the hostname, use the Pi's IP address. Set the LED count, key offset and brightness to match your strip before using the visualizer.

## MIDI setup

### USB piano

Connect the piano to the Pi and open **Ports Settings** in the web interface.

Choose **Auto** under **Active** to let the visualizer select an available input. It keeps the current device when another one appears and waits for a device when none is connected. You can also select a specific input by name.

Auto selects local device inputs; RTP-MIDI, Midi Through and internal Pi ports are excluded. Select a network session explicitly when using RTP-MIDI. The LCD offers the same Auto choice under **Ports Settings → Input**.

The playback output is a separate setting. Choose the destination under **Playback**, or disable it when you only need the LEDs.

### OSC Midi Tool and RTP-MIDI

1. Start [OSC Midi Tool](https://github.com/GoulagmanYt/RTP-OSC-Midi-tool) on your computer and configure its MIDI routing.
2. In **Ports Settings**, select the peer in **RTP MIDI Auto-Connect**.
3. Choose the input and playback output for the direction you need. For example, a USB piano can be the input and `rtpmidid:OSCMidi` the playback output.

See [RTP-MIDI setup and stability](Docs/rtpmidi_stability.md) for service configuration and troubleshooting.

## Performance and diagnostics

MIDI reception, LED rendering and network forwarding use separate queues and workers. The web diagnostics report queue depths, message counters, connection state and timing measurements.

Network latency depends on the full route. Tests on the documented Wi-Fi setup still show occasional delays and packet loss. The [latency report](Docs/rtp_latency_2026-10-18.md) includes the test method and results; the [RTP loss investigation](Docs/rtp_loss_origin_2026-10-18.md) records a QoS configuration that made delivery worse.

Treat clock, voltage and governor settings as specific to the board and workload. Check temperature and throttling on your own Pi before keeping a change.

## Updating

Use **Settings → Update Visualizer** in the web interface, or run the updater over SSH:

```bash
cd /home/Piano-LED-Visualizer
sudo python3 scripts/reliable_update.py --project-dir /home/Piano-LED-Visualizer
```

The updater fetches this fork's `master` branch, validates the release and backs up configuration and user data. It restarts the service, checks the HTTP health endpoint and attempts rollback if activation or the health check fails. Uncommitted source changes block the update.

## Documentation

| Guide | Contents |
| --- | --- |
| [Installation](Docs/manual_installation.md) | OS setup, dependencies, SPI and service configuration |
| [Features](Docs/features.md) | LED modes, songs, learning and sequences |
| [Wi-Fi setup](Docs/wifi_setup.md) | Headless network configuration |
| [Automatic hotspot](Docs/autohotspot.md) | Access point configuration |
| [RTP-MIDI](Docs/rtpmidi_stability.md) | Network MIDI services and reconnection |
| [External devices](Docs/external_devices.md) | Buttons, sensors and other controls |
| [Cover detection](Docs/cover_detection.md) | Piano cover sensor setup |
| [MIDI diagnostics](Docs/midi_debug_2026-10-18.md) | Delivery checks and pipeline investigation |

## Development

The application entry point is `visualizer.py`. MIDI handling, LED effects and device support live in `lib/`; the Flask application and browser assets are in `webinterface/`. Regression tests are in `tests/`.

On a Raspberry Pi development installation with the required system libraries:

```bash
python3 -m venv --system-site-packages .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q --ignore=tests/test_screen.py
```

`test_screen.py` needs a physical Pi display. Some MIDI tests also access host services, so run them in a development environment with no production instance running.

The Ports page has additional DOM tests. With Node.js and npm installed:

```bash
npm install --prefix .maintenance/input-auto-web --no-save --package-lock=false jsdom@31.0.0
NODE_PATH="$PWD/.maintenance/input-auto-web/node_modules" node --test tests/test_ports_ui.cjs
```

For a bug report, include your board, OS version, MIDI device names, reproduction steps and relevant service logs. For port or timing changes, add a regression test and describe which parts were checked on hardware. Use [issues](https://github.com/GoulagmanYt/Piano-LED-Visualizer/issues) for reports and feature requests.

## Credits and license

Based on [onlaj/Piano-LED-Visualizer](https://github.com/onlaj/Piano-LED-Visualizer), with Zero 2 W and OSC Midi Tool integration maintained in this fork by GoulagmanYt.

The Pacifica animation is by Mark Kriegsman and Mary Corey March (FastLED). The Meteor Rain effect is based on the Tweaking4All example.

Released under the [MIT license](LICENSE).
