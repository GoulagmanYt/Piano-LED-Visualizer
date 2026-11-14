#!/bin/bash
set -euo pipefail

REPO_URL="https://github.com/GoulagmanYt/Piano-LED-Visualizer.git"
REPO_BRANCH="master"
APP_DIR="/home/Piano-LED-Visualizer"
PLV_USER="plv"
PLV_CREATED_ACCOUNT=0
PLV_HOSTNAME="pianoledvisualizer"

# Restrict OS/architecture before making any changes to the machine.
detect_platform() {
  local version_codename arch
  version_codename="$(. /etc/os-release; printf '%s' "${VERSION_CODENAME:-}")"
  arch="$(dpkg --print-architecture)"
  case "$version_codename:$arch" in
    bookworm:armhf|bookworm:arm64|trixie:armhf|trixie:arm64) ;;
    *) display_error "Unsupported OS/architecture: ${version_codename:-unknown}/$arch (expected Bookworm or Trixie on armhf or arm64)" ;;
  esac
  PLV_OS="$version_codename"
  PLV_ARCH="$arch"
}

# Function to display error message and exit
display_error() {
  echo "Error: $1" >&2
  exit 1
}

# Execute commands, retrying network operations against their actual endpoint.
execute_command() {
  local check_internet="${2:-}"  # Legacy argument: retry network operations

  echo "Executing: $1"

  if [ "$check_internet" = "check_internet" ]; then
    local max_retries=18  # Total number of retries (18 retries * 10 seconds = 3 minutes)
    local retry_interval=10  # Retry interval in seconds

    local attempt exit_code
    for ((attempt = 1; attempt <= max_retries; attempt++)); do
      # ICMP may be blocked even when apt/Git/HTTPS work. Let the operation
      # itself determine connectivity, including its DNS/proxy/TLS settings.
      exit_code=0
      eval "$1" || exit_code=$?
      if [ "$exit_code" -eq 0 ]; then
        return 0
      fi
      echo "Command failed with exit code $exit_code (Attempt $attempt/$max_retries)."
      if [ "$attempt" -lt "$max_retries" ]; then
        sleep "$retry_interval"
      fi
    done

    echo "Command failed after $((max_retries * retry_interval)) seconds of retries."
    exit 1  # Exit the script after multiple unsuccessful retries
  else
    local exit_code=0
    eval "$1" || exit_code=$?  # Execute the command without internet connectivity check
    if [ $exit_code -ne 0 ]; then
      echo "Command failed with exit code $exit_code."
      exit $exit_code
    fi
  fi
}



# Function to update the OS
update_os() {
  execute_command "sudo apt-get update" "check_internet"
  execute_command "sudo apt-get upgrade -y"
}

configure_pi_identity() {
  local user_groups=""
  for group in audio video input render plugdev dialout netdev spi i2c gpio; do
    if getent group "$group" >/dev/null 2>&1; then
      user_groups="${user_groups:+${user_groups},}${group}"
    fi
  done

  execute_command "sudo hostnamectl set-hostname ${PLV_HOSTNAME}"
  execute_command "sudo sed -i -E 's/^(127\\.0\\.1\\.1\\s+).*/\\1${PLV_HOSTNAME}/' /etc/hosts"
  if ! getent hosts "${PLV_HOSTNAME}" >/dev/null 2>&1; then
    echo "127.0.1.1 ${PLV_HOSTNAME}" | sudo tee -a /etc/hosts >/dev/null
  fi

  if ! id -u "${PLV_USER}" >/dev/null 2>&1; then
    execute_command "sudo useradd -m -s /bin/bash -G ${user_groups} ${PLV_USER}"
    # Keep the account locked until private credentials are provisioned later.
    PLV_CREATED_ACCOUNT=1
  fi

  execute_command "sudo usermod -aG ${user_groups} ${PLV_USER}"

  if systemctl list-unit-files ssh.service --no-legend 2>/dev/null | grep -q '^ssh\.service'; then
    execute_command "sudo systemctl enable ssh.service"
    execute_command "sudo systemctl start ssh.service"
  fi
}

# Function to enable SPI interface
enable_spi_interface() {
  # Edit config.txt file to enable SPI interface
  execute_command "sudo raspi-config nonint do_spi 0"
}

# Function to install required packages
install_packages() {
  local os_packages
  if [ "$PLV_OS" = "trixie" ]; then
    os_packages="libasound2t64 cmake pkg-config ninja-build libfmt-dev"
  else
    os_packages="libasound2 libfmt9 libatlas-base-dev"
  fi
  execute_command "sudo apt-get install -y ca-certificates openssh-client ruby git wget iw python3-pip python3-venv autotools-dev libtool autoconf libavahi-client3 libavahi-common3 libc6 libgcc-s1 libstdc++6 python3 libopenblas-dev libavahi-client-dev libasound2-dev libusb-dev libdbus-1-dev libglib2.0-dev libudev-dev libical-dev libreadline-dev libopenjp2-7 libtiff6 libjack0 libjack-dev fonts-freefont-ttf libfreetype6 gcc make build-essential scons swig abcmidi overlayroot ${os_packages}" "check_internet"
}

# Function to disable audio output and configure fast boot
disable_audio_output() {
  echo 'blacklist snd_bcm2835' | sudo tee -a /etc/modprobe.d/snd-blacklist.conf > /dev/null
  local boot_config="/boot/firmware/config.txt"
  if [ ! -f "$boot_config" ]; then
    boot_config="/boot/config.txt"
  fi
  sudo sed -i 's/^dtparam=audio=on/#dtparam=audio=on/' "$boot_config"
  for cfg in "initial_turbo=30" "disable_splash=1" "boot_delay=0"; do
    key=$(echo "$cfg" | cut -d= -f1)
    if ! grep -q "^${key}=" "$boot_config"; then
      echo "$cfg" | sudo tee -a "$boot_config" > /dev/null
    fi
  done
}

# Function to install RTP-midi server
install_rtpmidi_server() {
  execute_command "sudo python3 ${APP_DIR}/scripts/install_rtpmidid.py --os ${PLV_OS} --arch ${PLV_ARCH}" "check_internet"
}


# Function to install Piano-LED-Visualizer
install_piano_led_visualizer() {
  if [ -d "${APP_DIR}/.git" ]; then
    execute_command "sudo chown -R root:root ${APP_DIR}"
    execute_command "sudo git -C ${APP_DIR} remote set-url origin ${REPO_URL}"
    execute_command "sudo git -C ${APP_DIR} fetch origin ${REPO_BRANCH}" "check_internet"
    execute_command "sudo git -C ${APP_DIR} checkout ${REPO_BRANCH}"
    execute_command "sudo git -C ${APP_DIR} pull --ff-only origin ${REPO_BRANCH}" "check_internet"
  else
    if [ -e "${APP_DIR}" ]; then
      execute_command "sudo mv ${APP_DIR} ${APP_DIR}.pre-autoinstall-$(date +%Y%m%d-%H%M%S)"
    fi
    execute_command "cd /home/ && sudo git clone --branch ${REPO_BRANCH} ${REPO_URL} ${APP_DIR}" "check_internet"
  fi

  execute_command "sudo git -C ${APP_DIR} config --local pull.ff only"
  execute_command "sudo git -C ${APP_DIR} config --local core.filemode false"
  execute_command "sudo python3 -m venv ${APP_DIR}/.venv"
  execute_command "sudo ${APP_DIR}/.venv/bin/python -m pip install -r ${APP_DIR}/requirements.txt" "check_internet"
  if [ "${PLV_CREATED_ACCOUNT:-0}" = 1 ]; then
    execute_command "sudo bash ${APP_DIR}/scripts/secure_installation.sh --initialize-account"
  else
    execute_command "sudo bash ${APP_DIR}/scripts/secure_installation.sh"
  fi
  execute_command "sudo raspi-config nonint do_boot_behaviour B2"
  execute_command "sudo install -m 0644 ${APP_DIR}/systemd/visualizer.service /lib/systemd/system/visualizer.service"
  execute_command "sudo systemctl daemon-reload"
  execute_command "sudo systemctl enable visualizer.service"
}

apply_default_runtime_tuning() {
  echo "Applying default Raspberry Pi runtime tuning..."
  execute_command "sudo chmod +x ${APP_DIR}/scripts/*.sh 2>/dev/null || true"
  execute_command "sudo bash ${APP_DIR}/scripts/configure_rtpmidi_stability.sh rtpmidid"
  execute_command "sudo env PLV_DIR=${APP_DIR} bash ${APP_DIR}/scripts/configure_pi_low_latency.sh"
  execute_command "sudo systemctl enable visualizer.service rtpmidid.service plv-lowlatency.service"
  execute_command "sudo systemctl restart rtpmidid.service"
  execute_command "sudo systemctl restart visualizer.service"
  execute_command "systemctl is-active visualizer.service"
  execute_command "systemctl is-active rtpmidid.service"
  execute_command "systemctl is-active plv-lowlatency.service"
  execute_command "sudo git -C ${APP_DIR} status --short --branch"
  echo ""
  echo "======================================================================"
  echo "PLV TUNING: Fast Boot enabled (~12s)."
  echo "To enable Safe Power Off protection (read-only OverlayFS):"
  echo "  sudo bash ${APP_DIR}/scripts/enable_safe_poweroff.sh"
  echo "To return to read-write mode:"
  echo "  sudo bash ${APP_DIR}/scripts/disable_safe_poweroff.sh"
  echo "======================================================================"
  echo ""
}

finish_installation() {
  echo "------------------"
  echo "------------------"
  echo "Installation complete. Raspberry Pi will automatically restart in 60 seconds."
  echo "If the Raspberry Pi does not restart on its own, please wait for 2 minutes and then manually reboot."
  echo "After the reboot, please wait for up to 10 minutes. The Visualizer should start, and the Hotspot 'PianoLEDVisualizer' will become available."

  execute_command "sudo shutdown -r +1"
  sleep 60
  # Reboot Raspberry Pi
  execute_command "sudo reboot"
}

echo "
#    _____  _                        _       ______  _____
#   |  __ \\(_)                      | |     |  ____||  __ \\
#   | |__) |_   __ _  _ __    ___   | |     | |__   | |  | |
#   |  ___/| | / _\` || '_ \\  / _ \\  | |     |  __|  | |  | |
#   | |    | || (_| || | | || (_) | | |____ | |____ | |__| |
#   |_|    |_| \\__,_||_| |_| \\___/  |______||______||_____/
#   __      __ _                     _  _
#   \\ \\    / /(_)                   | |(_)
#    \\ \\  / /  _  ___  _   _   __ _ | | _  ____ ___  _ __
#     \\ \\/ /  | |/ __|| | | | / _\` || || ||_  // _ \\| '__|
#      \\  /   | |\\__ \\| |_| || (_| || || | / /|  __/| |
#       \\/    |_||___/ \\__,_| \\__,_||_||_|/___|\\___||_|
#
# Autoinstall script
# - maintained by GoulagmanYt, based on the original Onlaj installer
"

# Main script execution
detect_platform
configure_pi_identity
update_os
enable_spi_interface
install_packages
disable_audio_output
install_piano_led_visualizer
install_rtpmidi_server
apply_default_runtime_tuning
finish_installation
