# Preinstalled Raspberry Pi image

Run **Build Piano LED Visualizer Image** from GitHub Actions after pushing the
changes. The workflow builds Raspberry Pi OS Lite Bookworm **armhf**, matching
the working Pi Zero 2 W's OS and architecture. It installs the exact selected
commit, not whichever commit happens to be on master later.

Download the resulting artifact ZIP and extract it. Verify `plv.img.gz` against
`plv.img.gz.sha256`, then select the `.img.gz` with **Use custom** in Raspberry Pi
Imager. PiShrink enables filesystem expansion on first boot; allow that boot to
finish before disconnecting power.

The image includes the app and its Python venv, RTP-MIDI, SPI, Wi-Fi power-save
configuration, runtime tuning and LED shutdown safety. It uses repository
defaults, not the maintainer's settings, MIDI devices or songs. Board-specific
undervolting, clock limits and disabled Bluetooth/HDMI from the maintainer's Pi
are deliberately not imposed on every installation.

The default account is **plv**, password **visualizer**, with passwordless sudo
and SSH enabled. Change the password with `passwd` on first login. Each card
generates unique SSH host keys and a machine ID. No Wi-Fi credentials are baked
into the image. Configure networking before headless use; see
[Wi-Fi setup](wifi_setup.md). After connection, open
`http://pianoledvisualizer.local` and configure the LED strip and MIDI ports.

The build verifies Python dependencies/imports, systemd unit definitions and
enablement, the embedded commit, and the compressed output. It records the
commit in `/etc/plv-image-revision` and resolved Python versions in
`/etc/plv-python-packages.txt`. OS updates and compatible Python releases are
resolved during each build, so the result is traceable but not byte-identical.
Successful CI still needs a real SD-card boot test to confirm Wi-Fi, LCD,
LED output and USB/network MIDI on the target hardware.

`scripts/image-install.sh` is exclusively for the disposable CI chroot. It does
not start services or apply CPU/Wi-Fi tuning to the runner or an existing Pi.
