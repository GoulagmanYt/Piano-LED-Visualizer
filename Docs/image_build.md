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

The application account is **plv**. There is **no shared initial password** and
the downloaded image contains no generated login secret. Before the first boot,
choose an access method:

- Copy your **public** SSH key (for example `id_ed25519.pub`) onto the card's
  visible boot partition as `plv-authorized_keys`. Never copy the private key.
  First boot validates and imports this file without replacing existing keys,
  then removes the seed. Connect with `ssh plv@pianoledvisualizer.local` using
  the matching private key. This is the recommended headless access method.
- Alternatively, use Imager's supported account/network customization to create
  a separate administrator with a password you know and normal sudo access. The image preserves
  existing administrator accounts and the OS user setup service. That
  administrator can inspect `/var/lib/plv-bootstrap/initial-credentials.json`
  locally as root to recover the unique PLV password generated on that card.
  Passwords and SSH keys already configured for `plv` by Imager are preserved;
  a key-only account stays password-locked and needs no generated password.

Do not boot a headless card without configuring a key or administrator access;
there is no fallback public login. Initial passwords are stored root-only and
are never printed in boot logs or exposed through the web application. After
key login, `sudo /usr/local/sbin/plv-admin password` lets you choose a PLV
password without needing to know the generated one.

If the card will initially be reached through **PianoLEDVisualizer** rather
than an existing LAN, also create `plv-hotspot-password` on the boot partition
with a unique 8-63-byte passphrase you choose. The first boot imports and
removes this seed, so you know the PSK before attempting that first connection.
Without this seed, a random per-card PSK is generated; initial access must then
use a configured LAN or console. From a PLV session on that LAN,
`sudo /usr/local/sbin/plv-admin hotspot-password` prompts for a new PSK without
printing it and restarts the service. See [Wi-Fi setup](wifi_setup.md).

The normal OS account setup runs when `userconf`/`userconf.txt` was explicitly
provided. With a key seed or an already configured account, its interactive
console dialog is skipped so it cannot block first-boot SSH. Without either,
the console setup remains available. If that setup renames the first account
to your administrator, first boot creates a separate restricted `plv` account.

New PLV accounts are outside the `sudo` group. Their passwordless administration
access is restricted to the fixed actions documented in
[manual installation](manual_installation.md); the application files and venv
are owned by root. Existing administrators retain their password-based sudo.
Each card generates unique SSH host keys and a machine ID. No Wi-Fi credentials
are baked into the image. Configure networking before headless use; see
[Wi-Fi setup](wifi_setup.md). After connection, open
`http://pianoledvisualizer.local` and configure the LED strip and MIDI ports.

The build verifies Python dependencies/imports, systemd unit definitions and
enablement, the embedded commit, and the compressed output. It records the
commit in `/etc/plv-image-revision` and resolved Python versions in
`/etc/plv-python-packages.txt`. OS updates and compatible Python releases are
resolved during each build, so the result is traceable but not byte-identical.
Successful CI still needs a real SD-card boot test to confirm Wi-Fi, LCD,
LED output and USB/network MIDI on the target hardware.

The base OS checksum is pinned from the Raspberry Pi download's published
`.sha256` file. PiShrink is pinned to both a source commit and SHA256, checked
before execution. RTP-MIDI packages/source use the reviewed pins in
`scripts/install_rtpmidid.py`; changed or unavailable artifacts fail the build.
See the provenance and update procedure in
[manual installation](manual_installation.md#download-integrity).

`scripts/image-install.sh` is exclusively for the disposable CI chroot. It does
not start services or apply CPU/Wi-Fi tuning to the runner or an existing Pi.
