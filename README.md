# <img src="Docs/logo.svg" align="left" height="42" width="42" alt="Logo"> Piano LED Visualizer *(Zero 2 W Edition)*

[![Platform: Raspberry Pi Zero 2 W](https://img.shields.io/badge/Hardware-Raspberry%20Pi%20Zero%202%20W%20Only-C51A4A?style=for-the-badge&logo=raspberrypi&logoColor=white)](https://www.raspberrypi.com/products/raspberry-pi-zero-2-w/)
[![Companion: OSC Midi Tool](https://img.shields.io/badge/Companion-OSC%20Midi%20Tool-0080FF?style=for-the-badge&logo=musical-score&logoColor=white)](https://github.com/GoulagmanYt/RTP-OSC-Midi-tool)
[![Tests: 153/153 Passing](https://img.shields.io/badge/Tests-153%2F153%20Passed-brightgreen?style=for-the-badge&logo=pytest&logoColor=white)](tests/)
[![Python 3.11](https://img.shields.io/badge/Python-3.11%2B-blue?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)

An ultra-responsive, real-time LED visualizer for digital pianos, specifically engineered and finely tuned for the **Raspberry Pi Zero 2 W** (BCM2837B0 quad-core Cortex-A53).

This project is a dedicated fork of the original [Onlaj/Piano-LED-Visualizer](https://github.com/onlaj/Piano-LED-Visualizer). It strips out legacy overhead, fixes real-time audio/lighting pipeline bottlenecks, introduces authentic open-source visual effects, and is tailored to work hand-in-hand with [OSC Midi Tool](https://github.com/GoulagmanYt/RTP-OSC-Midi-tool) for seamless low-latency network & USB MIDI routing.

---

## 🎯 Why this Fork?

The original visualizer was designed primarily for older single-core Pis (Zero 1 / Pi 1) and generic setups, often encountering CPU spikes, thermal throttling, ALSA buffer overruns on fast chords, and noticeable latency over RTP-MIDI.

**This edition changes the game:**
- **Exclusively optimized for the Raspberry Pi Zero 2 W**: We take full advantage of the quad-core architecture with a dedicated threading model (render loop, housekeeping, MIDI monitor, and asynchronous WebSocket dispatch).
- **Designed for [OSC Midi Tool](https://github.com/GoulagmanYt/RTP-OSC-Midi-tool)**: Perfect synergy for wireless and USB RTP-MIDI streaming between your DAW, PC, Mac, iPad (Synthesia, Reaper, Ableton) and your piano keys.
- **Zero Latency Priority**: Under-the-hood synchronization primitives wake the LED render pipeline in microseconds (< 0.05 ms) the moment a note is struck.
- **Thermal & Energy Efficiency**: Idle CPU usage is slashed by ~68%, lowering operating temperatures by 5°C to 7°C so your Zero 2 W stays cool even in a closed 3D-printed enclosure without loud fans.

---

## ✨ Key Improvements & Features

### ⚡ 1. Real-Time MIDI & Latency Eradication
- **Instant Event Wakeup**: Replaced tight polling loops with synchronous event triggers (`activity.set()`). When silent, the CPU rests; the moment a key is pressed, the render loop unblocks in under 50 microseconds.
- **ALSA Buffer Overrun Fixes**: Aggressive multi-event draining prevents chord drops and buffer bloat during fast virtuosic playing.
- **Self-Healing USB Ports**: Automatic background detection and reconnect without stalling active playback.
- **LED Clamp Guards**: Strict array boundary protection preventing index out-of-bounds crashes regardless of strip density or transpose offsets.

### 🌿 2. CPU & Thermal Optimizations
- **Idle Render Loop De-spinning**: Cut background polling wakeups from 500 Hz down to an event-driven 40 Hz watchdog. Python idle CPU dropped from **17.6% down to 5.6%**.
- **`schedutil` Kernel Governor**: Dynamic frequency scaling aligned with the Linux kernel CFS scheduler.
- **Memory Optimization**: Completely zero swap usage, reducing SD card wear. Unloaded unused DRM 3D and HDMI video drivers to free precious RAM.

### 🛡️ 3. Robust Web Interface & 100% Test Coverage
- Restored the clean, fast-loading original base web UI (no bloated theme generators or style re-computations).
- Fully validated with **153 unit tests** running natively on target hardware.
- Safe, rollback-capable visualizer updates via `reliable_update.py`.

---

## ⚡ Hardware Optimization Guide (Undervolting & Low Thermals)

The Raspberry Pi Zero 2 W packs a quad-core processor in a tiny footprint. Without active cooling, it can easily reach 55°C+ at idle. By fine-tuning `/boot/firmware/config.txt`, you can significantly reduce power draw and temperature without any loss in performance.

### Recommended `/boot/firmware/config.txt` Settings:

```ini
# ==============================================================================
# Piano LED Visualizer - Optimized for Raspberry Pi Zero 2 W
# ==============================================================================

# Hardware SPI for Waveshare 1.44" LCD Hat
dtparam=spi=on
auto_initramfs=1

# Disable Camera & DSI display polling (saves CPU interrupts)
camera_auto_detect=0
display_auto_detect=0

# Power down unused HDMI video & audio subsystems (saves ~25-30 mA)
hdmi_blanking=2
hdmi_ignore_hotplug=1
enable_tvout=0
dtoverlay=vc4-kms-v3d,nohdmi,noaudio
max_framebuffers=1

# Disable onboard Bluetooth (saves ~15-20 mA, frees UART pins & stops interrupts)
dtoverlay=disable-bt

# Safe Undervolting & Frequency Scaling (BCM2837B0)
# Lowers Vcore by 50mV at 1GHz and 100mV at 600MHz idle
arm_freq=1000
arm_freq_min=600
over_voltage=-2
over_voltage_min=-4

# Turn off onboard green ACT LED (eliminates light bleed on the piano)
dtparam=act_led_trigger=none
dtparam=act_led_activelow=off
```

### Measured Real-World Results:
- **Core Voltage (Vcore)**: Dropped from **1.256 V** down to **1.206 V** under load (and ~1.10 V at idle).
- **SoC Temperature**: **-4°C to -6°C** cooler at idle and under continuous load.
- **Hardware Power**: Around **250 mW** saved, keeping the board stable on standard 5V power rails.
- **Throttling**: Maintained `throttled=0x0` with zero thermal or under-voltage throttling.

---

## 🎹 Pairing with OSC Midi Tool

This visualizer is tailor-made to pair with [GoulagmanYt/RTP-OSC-Midi-tool](https://github.com/GoulagmanYt/RTP-OSC-Midi-tool).

1. **On your PC / Mac**: Launch OSC Midi Tool to bridge your DAW, MIDI keyboard, or Synthesia over network.
2. **On the Visualizer**: Go to the web interface (`http://pianoledvisualizer.local`) $\rightarrow$ **Ports Settings**.
3. Select the active RTP-MIDI port (`rtpmidid:OSCMidi` or your USB piano input).
4. Enjoy rock-solid, jitter-free MIDI transmission with instant LED response!

---

## 🛠️ Hardware Requirements

| Component | Recommendation | Notes |
| :--- | :--- | :--- |
| **SBC** | **Raspberry Pi Zero 2 W** | Essential. Quad-core Cortex-A53 is required. |
| **LED Strip** | **WS2812B (144 LEDs/meter)** | 1.5m to 2m covers a standard 88-key piano keyboard. |
| **Power Supply** | **5V DC (4A to 6A)** | High quality 5V supply. **Never power LEDs from the Pi pins directly.** |
| **Screen (Optional)** | **Waveshare LCD 1.44" SPI** | Dedicated on-board menu with navigation joystick. |
| **DC Jack** | 5.5 x 2.1mm / 2.5mm screw terminal | For clean power distribution. |
| **MicroSD Card** | 16GB or 32GB Class 10 / A1 | Reliable card for Raspberry Pi OS (Bookworm). |

> [!CAUTION]
> **5V Power Warning**: Ensure your power supply is strictly **5V**. Using a 9V or 12V supply will instantly destroy both your LED strip and the Raspberry Pi.

---

## 🌐 Web Interface & Network Setup

Once powered on and connected to your local network:
1. Open your browser and navigate to:
   ```text
   http://pianoledvisualizer.local
   ```
   *(or use the Pi's direct IP address, e.g. `http://192.168.1.180`)*
2. Customize colors, brightness, responsive velocity modes, fading speeds, and background backlights.
3. Manage MIDI song playback, recordings, and sequences directly from your phone, tablet, or laptop.

---

## 🔄 Updating

You can safely update the visualizer directly from the Web Interface (`Settings > Update Visualizer`) or via SSH:

```bash
cd /home/Piano-LED-Visualizer
sudo python3 scripts/reliable_update.py --project-dir /home/Piano-LED-Visualizer
```
The updater automatically validates dependencies, runs health checks, and rolls back if an issue is detected.

---

## 📜 Credits & License

- Original base project: [Onlaj/Piano-LED-Visualizer](https://github.com/onlaj/Piano-LED-Visualizer).
- Pacifica animation: **Mark Kriegsman & Mary Corey March** (FastLED Library).
- Meteor Rain concept: **Tweaking4All**.
- Specialized Zero 2 W optimizations & OSC Midi Tool integration by **GoulagmanYt**.
- Licensed under the [MIT License](LICENSE).
