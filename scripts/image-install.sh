#!/usr/bin/env bash
# Run only inside the disposable image chroot, never against a live Pi.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
APP=/home/Piano-LED-Visualizer
PYTHON="$APP/.venv/bin/python"
test "$(dpkg --print-architecture)" = armhf
test "$(. /etc/os-release; echo "$VERSION_CODENAME")" = bookworm
test -x /usr/sbin/policy-rc.d

apt-get update
apt-get -y -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold upgrade
apt-get install -y git curl ca-certificates python3-pip python3-venv python3-dev \
  build-essential pkg-config gfortran meson ninja-build cmake \
  libopenblas-dev libasound2-dev libjack-dev libavahi-client-dev libfmt9 \
  libjpeg-dev zlib1g-dev libfreetype6-dev libopenjp2-7 libtiff6 \
  fonts-freefont-ttf scons swig abcmidi iw avahi-daemon openssh-server

echo pianoledvisualizer > /etc/hostname
sed -i -E 's/^(127\.0\.1\.1\s+).*/\1pianoledvisualizer/' /etc/hosts
groups=sudo
for group in audio video input render plugdev dialout netdev spi i2c gpio; do
  if getent group "$group" >/dev/null; then groups="$groups,$group"; fi
done
if ! id -u plv >/dev/null 2>&1; then
  useradd -m -G "$groups" -s /bin/bash plv
fi
echo 'plv:visualizer' | chpasswd
echo 'plv ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/010_pi-nopasswd
chmod 0440 /etc/sudoers.d/010_pi-nopasswd
if id -u pi >/dev/null 2>&1; then userdel -r pi; fi
# A preconfigured account replaces the stock interactive user setup.
systemctl disable userconfig.service 2>/dev/null || true
systemctl set-default multi-user.target

curl --fail --location --retry 3 -o /tmp/rtpmidid.deb \
  https://github.com/davidmoreno/rtpmidid/releases/download/v24.12/rtpmidid_24.12.2_armhf.deb
apt-get install -y /tmp/rtpmidid.deb
rm /tmp/rtpmidid.deb

python3 -m venv "$APP/.venv"
"$PYTHON" -m pip install --upgrade pip
"$PYTHON" -m pip install -r "$APP/requirements.txt"
"$PYTHON" -m pip freeze > /etc/plv-python-packages.txt
git -C "$APP" rev-parse HEAD > /etc/plv-image-revision
cp "$APP/config/default_settings.xml" "$APP/config/settings.xml"
chown -R plv:plv "$APP"

BOOT=/boot/firmware/config.txt
sed -i 's/^dtparam=audio=on/#dtparam=audio=on/' "$BOOT"
cat >> "$BOOT" <<'EOF'

[all]
dtparam=spi=on
initial_turbo=30
disable_splash=1
boot_delay=0
EOF
echo 'blacklist snd_bcm2835' > /etc/modprobe.d/snd-blacklist.conf

install -m 0644 "$APP/systemd/visualizer.service" /etc/systemd/system/visualizer.service
mkdir -p /etc/systemd/system/visualizer.service.d /etc/systemd/system/rtpmidid.service.d
cat > /etc/systemd/system/visualizer.service.d/override.conf <<EOF
[Unit]
After=local-fs.target plv-lowlatency.service
Wants=plv-lowlatency.service

[Service]
RestartSec=1
SupplementaryGroups=audio gpio spi i2c video input render
Nice=-10
IOSchedulingClass=realtime
IOSchedulingPriority=0
LimitRTPRIO=10
LimitNICE=-10
LimitMEMLOCK=64M
EOF
# The same LED cleanup and scheduling safeguards as the live Pi.
python3 "$APP/scripts/configure_service_safety.py"
cat > /etc/systemd/system/rtpmidid.service.d/override.conf <<'EOF'
[Unit]
After=network-online.target
Wants=network-online.target
[Service]
Restart=always
RestartSec=2
EOF
mkdir -p /etc/NetworkManager/conf.d
cat > /etc/NetworkManager/conf.d/30-wifi-powersave-off.conf <<'EOF'
[connection]
wifi.powersave=2
EOF

# Share runtime tuning with the installer; never run it against the build host.
install -m 0755 "$APP/scripts/plv-lowlatency-apply.sh" /usr/local/sbin/plv-lowlatency-apply.sh
cat > /etc/systemd/system/plv-lowlatency.service <<'EOF'
[Unit]
Description=Piano LED Visualizer runtime tuning
After=local-fs.target
Before=visualizer.service
[Service]
Type=oneshot
ExecStart=/usr/local/sbin/plv-lowlatency-apply.sh
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
EOF

# Each flashed card gets its own SSH host keys; none are shipped in the image.
cat > /etc/systemd/system/plv-first-boot.service <<'EOF'
[Unit]
Description=Generate unique SSH host keys
Before=ssh.service
After=local-fs.target
[Service]
Type=oneshot
ExecStart=/usr/bin/ssh-keygen -A
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
EOF
systemctl enable visualizer.service rtpmidid.service plv-lowlatency.service \
  plv-first-boot.service ssh.service avahi-daemon.service
