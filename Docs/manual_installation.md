# Installation on Raspberry Pi OS

The automatic installer targets Raspberry Pi OS Lite **Bookworm or Trixie** on
`armhf` or `arm64`. Trixie/armhf builds rtpmidid from source; this can take a
long time on a Pi Zero. Installation and updates need an internet connection.
Back up an existing installation before running the installer again.

1. Use Raspberry Pi Imager to install Raspberry Pi OS Lite, configure networking
   and enable SSH. See [Wi-Fi setup](wifi_setup.md) for a headless system.
2. Connect the LED strip to an appropriately sized 5 V supply and share ground
   with the Pi. Do not power the LED strip from the GPIO header.
3. Review the installer before running it. It upgrades OS packages, configures
   SPI, hostname and the `plv` account, installs services and applies Pi tuning.
   It sets the account password to `visualizer` and schedules a reboot. Change
   that password and review sudo access after installation.

   ```bash
   curl -fsSLo autoinstall.sh https://raw.githubusercontent.com/GoulagmanYt/Piano-LED-Visualizer/master/autoinstall.sh
   sudo bash autoinstall.sh
   ```

4. After reboot, open `http://pianoledvisualizer.local` or the Pi's IP address.
   Configure the LED count, key offset, brightness and MIDI ports.

The application is installed in `/home/Piano-LED-Visualizer`, with Python
packages in `.venv`. The systemd service and the LED stop-safety helper use the
same venv interpreter. Existing installations that still use system Python
continue to be supported by the updater; updating does **not** automatically
convert them to a venv. The installer retains the fork's in-app MIDI connection manager and low-latency
tuning, but no longer installs the legacy system MIDI mesh/udev scripts.

## Diagnostics and updates

```bash
sudo systemctl status visualizer.service rtpmidid.service
sudo journalctl -u visualizer.service -b --no-pager
```

Use the web interface's update action, which runs the updater with the service's
Python interpreter. If invoking it manually on a venv installation, use:

```bash
cd /home/Piano-LED-Visualizer
sudo .venv/bin/python scripts/reliable_update.py --project-dir "$PWD"
```

For a legacy system-Python installation, use `sudo python3` instead. The updater
backs up user data, stops the service before installing dependencies, and
attempts to restore the old revision and its dependencies if activation fails.
A rollback depends on package availability; keep a separate backup of the SD
card and user data. See [RTP-MIDI stability](rtpmidi_stability.md) and
[Wi-Fi setup](wifi_setup.md) for additional diagnostics.

**Hardware validation:** package installation, SPI and RTP-MIDI behavior should
be verified on the target Pi and OS image. The automated tests simulate installer
commands; they do not install packages or exercise real GPIO/network hardware.
