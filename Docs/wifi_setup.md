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

The example assumes username `plv` and hostname `pianoledvisualizer`. This fork's autoinstaller sets that hostname and creates or configures the `plv` account with password `visualizer`; before running it, use your Imager credentials. Follow the [installation guide](manual_installation.md) once connected.

## Connect through the Visualizer hotspot

When the installed Visualizer has its hotspot enabled:

1. Join **PianoLEDVisualizer** from your phone or computer. The default hotspot password is `visualizer`; use your saved password if you changed it in the web interface.
2. Open `http://pianoledvisualizer.local`. If it does not resolve, use the hotspot gateway address shown in your device's Wi-Fi details, commonly `http://10.42.0.1`.
3. Open the **Network** tab and enter your home Wi-Fi credentials.
4. When the Pi joins your home network, reconnect your phone or computer to that network and reopen the web interface using the hostname or the Pi's new LAN address.

If the web connection attempt fails, use the SSH method below to create an explicit NetworkManager client profile.

## Configure a client profile over SSH

These commands are for a WPA/WPA2 Personal network on `wlan0`. They create a separate client profile and leave the Visualizer's `Hotspot` profile intact.

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
