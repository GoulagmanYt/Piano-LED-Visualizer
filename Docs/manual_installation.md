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
   A newly created account gets a random, per-installation password, stored only
   in root-readable `/var/lib/plv-bootstrap/initial-credentials.json`; it is not
   printed in logs. Use your existing administrator account to inspect it
   locally, then connect as `plv`. Existing PLV passwords, SSH keys and group
   memberships are preserved. The installer schedules a reboot.

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

New `plv` accounts do not join the `sudo` group. The old PLV-specific
`NOPASSWD: ALL` grant is replaced by a root-owned administration helper, with
fixed actions and no user-selected program, path or update URL. Existing
administrators keep their password-based sudo access. Application code and the
venv are root-owned, so a PLV login cannot modify code later executed as root.
The service continues to run as root for WS281x DMA/GPIO; it uses a private
creation mask and cannot read the bootstrap credential directory. These are
limited protections, not a claim that a root web process is sandboxed.

After SSH key login, choose a password with
`sudo /usr/local/sbin/plv-admin password`. For image/headless provisioning, see
[the explicit key/administrator access steps](image_build.md).
New configurations also receive a unique hotspot PSK; existing configurations
are preserved. To know the PSK before connecting through a new card's hotspot,
provide a `plv-hotspot-password` boot seed. Otherwise use your configured LAN
or local console first, then choose a PSK with the hidden prompt provided by
`sudo /usr/local/sbin/plv-admin hotspot-password`. See
[Wi-Fi setup](wifi_setup.md) for both access paths. No public fallback PSK is
used if provisioning is missing or invalid.

## Diagnostics and updates

```bash
sudo /usr/local/sbin/plv-admin status
sudo /usr/local/sbin/plv-admin logs
```

Use the web interface's update action, which runs the updater with the service's
Python interpreter. If invoking it manually on a venv installation, use:

```bash
sudo /usr/local/sbin/plv-admin update
```

On an older installation without this helper, an existing administrator can run
`sudo python3 scripts/reliable_update.py --project-dir /home/Piano-LED-Visualizer`
from the project directory (or use `.venv/bin/python` if present). The updater
backs up user data, stops the service before installing dependencies, and
attempts to restore the old revision and its dependencies if activation fails.
A rollback depends on package availability; keep a separate backup of the SD
card and user data. See [RTP-MIDI stability](rtpmidi_stability.md) and
[Wi-Fi setup](wifi_setup.md) for additional diagnostics.

**Hardware validation:** package installation, SPI and RTP-MIDI behavior should
be verified on the target Pi and OS image. The automated tests simulate installer
commands; they do not install packages or exercise real GPIO/network hardware.

Other allowed helper actions are `restart`, `restart-midi`, `reboot` and
`poweroff`. Additional arguments and arbitrary commands are rejected. General OS
administration still requires your existing administrator account.

## Download integrity

RTP-MIDI installation verifies downloaded bytes before any package installation,
archive extraction or source build. Network failure and SHA256 mismatch are
hard errors; there is no unverified offline fallback. The supported pins live in
`scripts/install_rtpmidid.py`:

- Trixie/arm64 v26.01 uses the SHA256 published in the upstream
  [GitHub release metadata](https://api.github.com/repos/davidmoreno/rtpmidid/releases/tags/v26.01).
- Bookworm v24.12 legacy assets do not publish an API digest or signed checksum.
  Their static review-time SHA256 pins were obtained from the official HTTPS
  [release assets](https://api.github.com/repos/davidmoreno/rtpmidid/releases/tags/v24.12)
  (arm64 asset `213481992`, armhf asset `213524010`). These detect later content
  changes; they do not add an independent publisher signature to those releases.
- Trixie/armhf builds the archive for commit
  `c3a289cda674a7a3ec53c137d05caf5c42aa3f21`, with a separately reviewed SHA256
  pin. Source links and special archive members are rejected before extraction.

Updating a pin requires reviewing the new upstream release/commit and its
published digest or authenticating the official artifact out of band, then
changing the URL and expected digest together in a reviewed commit. Never
derive the expected digest from the download during installation. The image
workflow also pins the official Raspberry Pi OS checksum and the PiShrink
script's immutable source commit and checksum.

## Read-only SD card protection

The optional OverlayFS setup makes changes to settings and uploaded songs
temporary until the writable filesystem is restored. Check its state with:

```bash
sudo /usr/local/sbin/plv-admin protection-status
```

Before an update or permanent configuration change, run
`sudo /usr/local/sbin/plv-admin protection-disable`. After reboot, run the same
action again to restore boot writes if needed (it reboots the Pi). Make the
changes, then run `sudo /usr/local/sbin/plv-admin protection-enable` to restore protection.
Check the status again. Keep backups outside the Pi; OverlayFS does not protect
against every hardware or power failure.
