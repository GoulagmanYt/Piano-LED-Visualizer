# Piano LED Visualizer

[![Raspberry Pi Zero 2 W](https://img.shields.io/badge/hardware-Raspberry%20Pi%20Zero%202%20W-C51A4A?logo=raspberrypi&logoColor=white)](https://www.raspberrypi.com/products/raspberry-pi-zero-2-w/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Light up piano keys as you play. Piano LED Visualizer runs on a Raspberry Pi and drives a WS2812B LED strip from USB or network MIDI. A web interface handles colors, MIDI ports, song playback and recordings. An optional LCD provides local controls.

This fork of [onlaj/Piano-LED-Visualizer](https://github.com/onlaj/Piano-LED-Visualizer) targets the Raspberry Pi Zero 2 W. Work here focuses on MIDI delivery, reconnecting devices, reducing idle CPU use and integrating with [OSC Midi Tool](https://github.com/GoulagmanYt/RTP-OSC-Midi-tool).

[Installation](#installation) · [MIDI setup](#midi-setup) · [Documentation](#documentation) · [Development](#development)

## Features

- LED colors based on note, velocity or playing speed, with fading, backlight and animation settings.
- MIDI file playback, recording and guided practice, including an opt-in Synthesia Learning bridge.
- USB MIDI input with an Auto mode that keeps the current device connected and waits when no device is available.
- RTP-MIDI routing through rtpmidid, with peer selection and connection diagnostics in the web interface.
- Browser controls available in 12 languages, plus an optional Waveshare LCD menu.
- LED current and power estimates with calibration for your strip, under LED Settings.
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

Start with Raspberry Pi OS Lite Bookworm or Trixie (armhf or arm64). The [installation guide](Docs/manual_installation.md) covers OS setup, SPI, dependencies and the systemd service. For a headless setup, see the [Wi-Fi guide](Docs/wifi_setup.md).

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

### Synthesia Learning bridge

In **Ports Settings → Synthesia Learning bridge**, choose the four piano and
computer input/output ports, select **Learning**, save and restart the
visualizer. Disconnect direct MIDI links between those devices first. The
bridge routes guide lights separately from piano sound; see the
[setup and safety notes](Docs/features.md#learning_with_synthesia).

### OSC Midi Tool and RTP-MIDI

1. Start [OSC Midi Tool](https://github.com/GoulagmanYt/RTP-OSC-Midi-tool) on your computer and configure its MIDI routing.
2. In **Ports Settings**, select the peer in **RTP MIDI Auto-Connect**.
3. Choose the input and playback output for the direction you need. For example, a USB piano can be the input and `rtpmidid:OSCMidi` the playback output.

See [RTP-MIDI setup and stability](Docs/rtpmidi_stability.md) for service configuration and troubleshooting.

## Performance and diagnostics

MIDI reception, LED rendering and network forwarding use separate queues and workers. The web diagnostics report queue depths, message counters, connection state and timing measurements.

The [performance guide](Docs/performance.md) explains what each measurement covers and how to reproduce it. It links the measured MIDI pipeline, WebSocket and RTP/Wi-Fi results, including their limits. The documented Wi-Fi setup still shows occasional delays and packet loss; software timing is not physical key-to-light latency.

Treat clock, voltage and governor settings as specific to the board and workload. Check temperature and throttling on your own Pi before keeping a change.

## Updating

Use **Settings → Update Visualizer** in the web interface, or run the updater over SSH:

```bash
cd /home/Piano-LED-Visualizer
sudo .venv/bin/python scripts/reliable_update.py --project-dir /home/Piano-LED-Visualizer
```

On legacy installations using system Python instead of `.venv`, use `sudo python3` for this command. The updater fetches this fork's `master` branch, validates the release and backs up configuration and user data. It restarts the service, checks the HTTP health endpoint and attempts rollback if activation or the health check fails. Uncommitted source changes block the update.

## Documentation

| Guide | Contents |
| --- | --- |
| [Installation](Docs/manual_installation.md) | OS setup, dependencies, SPI and service configuration |
| [Preinstalled image](Docs/image_build.md) | Build and validate a Raspberry Pi image |
| [Features](Docs/features.md) | LED modes, songs, learning and sequences |
| [Wi-Fi setup](Docs/wifi_setup.md) | Headless networking, hotspot and recovery |
| [RTP-MIDI](Docs/rtpmidi_stability.md) | Network MIDI services and reconnection |
| [External devices](Docs/external_devices.md) | Buttons, sensors and other controls |
| [Cover detection](Docs/cover_detection.md) | Piano cover sensor setup |
| [Architecture](Docs/architecture.md) | Runtime components, MIDI routing and resource ownership |
| [Performance and measurements](Docs/performance.md) | Benchmark methods, latency, delivery and recorded results |

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

### Using another GPIO HAT

To free the LCD control HAT's GPIO pins and SPI0 for another HAT, set
`<disable_hat>1</disable_hat>` in `config/settings.xml` and restart the
visualizer service. The setting defaults to `0`; existing installations get
it from the default settings on startup. With it enabled the LCD, joystick,
buttons and cover sensor are unavailable (the cover is treated as open).
Control the visualizer through the web interface instead. The LED driver is
not disabled; choose its pin so it does not conflict with your other hardware.
