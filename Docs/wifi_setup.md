# Wi-Fi setup

Start with Raspberry Pi OS Lite Bookworm for this fork's current [installer](../autoinstall.sh). Configure Wi-Fi before installation so you can reach the Pi over SSH.

Raspberry Pi OS Bookworm uses [NetworkManager](https://www.raspberrypi.com/documentation/computers/configuration.html#connect-to-a-wireless-network). The old boot-partition `wpa_supplicant.conf` method no longer applies.

## Configure Wi-Fi with Raspberry Pi Imager

When writing the OS image with [Raspberry Pi Imager](https://www.raspberrypi.com/documentation/computers/getting-started.html#install-using-imager), use OS customisation to set:

- A hostname, such as `pianoledvisualizer`.
- Your username and password, and SSH access.
- Your Wi-Fi SSID, password and wireless country. The Zero 2 W needs a 2.4 GHz network.

Boot the Pi, then connect with the username and hostname you selected:

```bash
ssh plv@pianoledvisualizer.local
```

The example assumes username `plv` and hostname `pianoledvisualizer`. Before
installation, use your Imager account. New installations have no shared login
password: use a public SSH key seed or the unique credential recovered locally
by your existing administrator. Existing account passwords and keys are
preserved. Follow the [installation guide](manual_installation.md) and the
[image access steps](image_build.md) before booting a headless card.

## Connect through the Visualizer hotspot

When the installed Visualizer has its hotspot enabled:

1. Join **PianoLEDVisualizer** using your card's chosen hotspot password.
   For a new headless card that will be reached through its hotspot, first put
   your own 8-63-byte WPA passphrase in a file named `plv-hotspot-password` on
   the visible boot partition. Edit the file locally rather than putting a
   secret in command history. First boot imports and removes the seed. Add
   `plv-authorized_keys` as well if you want SSH access through that hotspot.
   There is no public fallback password. Existing installations retain their
   saved hotspot password.
2. Open `http://pianoledvisualizer.local`. If it does not resolve, use the hotspot gateway address shown in your device's Wi-Fi details, commonly `http://10.42.0.1`.
3. Open the **Network** tab and enter your home Wi-Fi credentials.
4. When the Pi joins your home network, reconnect your phone or computer to that network and reopen the web interface using the hostname or the Pi's new LAN address.

If the web connection attempt fails, use the SSH method below to create an explicit NetworkManager client profile.

Without a hotspot seed, a new installation generates a unique random PSK. You
must first reach it through a configured LAN or a local console, rather than
trying to join the hotspot with a guessed default. From a PLV SSH session on
that LAN, run `sudo /usr/local/sbin/plv-admin hotspot-password` to choose a
known PSK using a hidden prompt; the service then restarts. Alternatively, your
existing administrator can inspect the root-only
`/var/lib/plv-bootstrap/hotspot-credentials.json` locally. Neither the password
nor this file is exposed in logs or web settings responses. Changing the PSK
disconnects hotspot clients; reconnect using the password you chose.

## Configure a client profile over SSH

These commands are for a WPA/WPA2 Personal network on `wlan0`. They create a separate client profile and leave the Visualizer's `Hotspot` profile intact.
They require an existing administrator account with general sudo access. A new
restricted `plv` account should use the web interface's **Network** tab instead.

First inspect existing profiles:

```bash
nmcli -f NAME,UUID,TYPE connection show
```

Use an unused name for the client profile, such as `plv-home-wifi`. If that name already exists, choose another name and use it consistently below. Reserve `Hotspot` for the Visualizer's access point.

Replace `YourSSID` and `YourPassword`, keeping the quotes:

```bash
sudo nmcli connection add type wifi ifname wlan0 con-name plv-home-wifi \
  ssid "YourSSID" wifi-sec.key-mgmt wpa-psk wifi-sec.psk "YourPassword" \
  connection.autoconnect yes
```

If SSH is using Ethernet or your LAN, activate the profile directly:

```bash
sudo nmcli connection up plv-home-wifi
```

If SSH is using the Visualizer hotspot, run the switch in a separate systemd service so it can finish after SSH disconnects:

```bash
sudo systemd-run --unit=plv-wifi-switch --collect /bin/sh -c \
  'nmcli connection down Hotspot; nmcli connection up plv-home-wifi'
```

The hotspot connection will drop. Rejoin your home network, then reconnect to the Pi using its hostname or LAN address. This manual switch leaves the Visualizer's saved hotspot preference unchanged, so it may restore the hotspot at the next start. A successful connection through the web **Network** tab saves the client-mode preference.

After reconnecting, inspect the active connection or the switch log:

```bash
nmcli -f NAME,DEVICE connection show --active
sudo journalctl -b -u plv-wifi-switch --no-pager -n 50
```

## Find the Pi or recover access

If `.local` name resolution fails, find the Pi in your router's connected-device list and use its IP address for SSH and the web interface. The LCD's **System Info** screen can also show the local address.

For a failed network switch, use a local keyboard and display or reconnect through the hotspot if the Visualizer restores it. Inspect NetworkManager's log:

```bash
sudo journalctl -b -u NetworkManager --no-pager -n 100
```

To restore the existing Visualizer hotspot profile from a local console:

```bash
sudo nmcli connection up Hotspot
```
