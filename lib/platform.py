import threading
import time
import subprocess
from subprocess import call
import os
import filecmp
from shutil import copyfile
from lib.log_setup import logger
import re
import socket
import sys
import json
from pathlib import Path
from collections import defaultdict

HOSTS_FILE = "/etc/hosts"
# RFC 1123 label: 1-63 letters, digits or hyphens, never starting or ending with
# a hyphen (a leading "-" would be parsed as an option by hostnamectl).
HOSTNAME_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")


def _strip_local_suffix(name):
    """Retire le suffixe ".local" d'un nom d'hôte.

    str.rstrip('.local') retire des *caractères* (ex. 'piano' -> 'pian') : on retire
    donc uniquement le suffixe exact.
    """
    name = name.strip()
    if name.lower().endswith(".local"):
        name = name[: -len(".local")]
    return name


class Hotspot:
    def __init__(self, hotspot):
        self.hotspot_script_time = 0
        self.time_without_wifi = 0
        self.last_wifi_check_time = 0

        # Installation permissions are managed at deployment, never at startup.

class PlatformBase:
    def __getattr__(self, name):
        def method(*args, **kwargs):
            return False, f"Method '{name}' is not supported on this platform", ""
        return method


class PlatformNull(PlatformBase):
    def __getattr__(self, name):
        return self.pass_func

    def pass_func(self, *args, **kwargs):
        pass


class PlatformRasp(PlatformBase):
    MAINTAINED_REPO_URL = "https://github.com/GoulagmanYt/Piano-LED-Visualizer.git"
    HOTSPOT_CONNECTION_NAME = "Hotspot"
    HOTSPOT_SSID = "PianoLEDVisualizer"
    HOTSPOT_IFACE = "wlan0"
    DEFAULT_HOTSPOT_PASSWORD = None
    UPDATE_STATE_DIR = Path("/var/lib/piano-led-visualizer")
    UPDATE_UNIT = "plv-reliable-update"
    # Serialises "is an update running?" + "mark it as starting" so two quick
    # requests (double click) cannot both launch an updater.
    _update_lock = threading.Lock()

    @staticmethod
    def check_and_enable_spi():
        try:
            # Check if SPI is enabled by looking for spidev in /dev
            if not os.path.exists('/dev/spidev0.0'):
                logger.info("SPI is not enabled. Enabling SPI interface...")
                subprocess.run(['sudo', 'raspi-config', 'nonint', 'do_spi', '0'], check=True)
                logger.info("SPI has been enabled. A reboot may be required for changes to take effect.")
                return False
            return True
        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to enable SPI: {e}")
            return False
        except Exception as e:
            logger.warning(f"Error checking SPI status: {e}")
            return False

    
    @staticmethod
    def disable_system_midi_scripts():
        """Disable udev rules and systemd service that run the old connectall script"""
        try:
            # Disable the udev rule
            udev_rule_path = '/etc/udev/rules.d/33-midiusb.rules'
            if os.path.exists(udev_rule_path):
                logger.info("Disabling udev MIDI rule...")
                # Rename the file to disable it
                os.rename(udev_rule_path, udev_rule_path + '.disabled')
                subprocess.call(['sudo', 'udevadm', 'control', '--reload'])
                logger.info("udev MIDI rule disabled")
            
            # Disable the systemd service
            service_name = 'midi.service'
            try:
                # Stop the service
                subprocess.call(['sudo', 'systemctl', 'stop', service_name])
                # Disable the service
                subprocess.call(['sudo', 'systemctl', 'disable', service_name])
                logger.info(f"Systemd service {service_name} disabled")
            except:
                logger.info(f"Could not disable systemd service {service_name}")
                
        except Exception as e:
            logger.warning(f"Error disabling system MIDI scripts: {e}")

    def install_midi2abc(self):
        if not self.is_package_installed("abcmidi"):
            logger.info("Installing abcmidi")
            subprocess.call(['sudo', 'apt-get', 'install', 'abcmidi', '-y'])

    @classmethod
    def get_update_status(cls):
        status_path = cls.UPDATE_STATE_DIR / "update-status.json"
        try:
            with status_path.open("r", encoding="utf-8") as status_file:
                status = json.load(status_file)
                updated_at = int(status.get("updated_at", 0) or 0)
                if (
                    status.get("state") not in {"success", "no_update", "rolled_back", "failed"}
                    and updated_at
                    and time.time() - updated_at > 3600
                ):
                    return {
                        **status,
                        "state": "failed",
                        "message": "La mise à jour précédente a été interrompue",
                        "error": "État de mise à jour expiré",
                    }
                return status
        except (OSError, ValueError):
            return {"state": "idle", "message": "Aucune mise à jour en cours"}

    @classmethod
    def update_visualizer(cls):
        """Start the updater in an independent systemd transient service."""
        project_dir = Path(__file__).resolve().parent.parent
        updater = project_dir / "scripts" / "reliable_update.py"
        status_path = cls.UPDATE_STATE_DIR / "update-status.json"

        with cls._update_lock:
            current_status = cls.get_update_status()
            if current_status.get("state") not in {"idle", "success", "no_update", "rolled_back", "failed"}:
                return {"success": False, "error": "Une mise à jour est déjà en cours", **current_status}

            if not updater.is_file():
                return {"success": False, "error": f"Programme de mise à jour introuvable: {updater}"}

            try:
                cls.UPDATE_STATE_DIR.mkdir(parents=True, exist_ok=True)
                temporary_status = status_path.with_suffix(".json.tmp")
                temporary_status.write_text(json.dumps({
                    "state": "starting",
                    "message": "Démarrage de la mise à jour sécurisée",
                    "started_at": int(time.time()),
                    "updated_at": int(time.time()),
                }), encoding="utf-8")
                os.replace(temporary_status, status_path)
            except OSError as error:
                logger.error(f"Unable to initialize update state: {error}")
                return {"success": False, "error": f"Impossible d'initialiser la mise à jour: {error}"}

        geteuid = getattr(os, "geteuid", lambda: 1)
        unit_name = f"{cls.UPDATE_UNIT}-{int(time.time())}"
        command = [] if geteuid() == 0 else ["sudo"]
        command.extend([
            "systemd-run",
            f"--unit={unit_name}",
            "--collect",
            "--property=Type=exec",
            sys.executable,
            str(updater),
            "--project-dir",
            str(project_dir),
            "--state-dir",
            str(cls.UPDATE_STATE_DIR),
            "--remote-url",
            cls.MAINTAINED_REPO_URL,
        ])
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            logger.error(f"Unable to start reliable updater: {detail}")
            try:
                status_path.write_text(json.dumps({
                    "state": "failed",
                    "message": "Impossible de démarrer la mise à jour",
                    "error": detail,
                    "updated_at": int(time.time()),
                }), encoding="utf-8")
            except OSError:
                pass
            return {"success": False, "error": detail or "Impossible de démarrer la mise à jour"}
        logger.info("Reliable update started in %s", unit_name)
        return {"success": True, "state": "starting", "message": "Mise à jour sécurisée démarrée"}

    @staticmethod
    def shutdown():
        call("sudo /sbin/shutdown -h now", shell=True)

    @staticmethod
    def reboot():
        call("sudo /sbin/reboot now", shell=True)

    @staticmethod
    def restart_visualizer():
        call("sudo systemctl restart visualizer", shell=True)

    @staticmethod
    def restart_rtpmidid():
        call("sudo systemctl restart rtpmidid", shell=True)

    @staticmethod
    def is_package_installed(package_name):
        try:
            # Run the 'dpkg' command to check if the package is installed
            result = subprocess.run(['dpkg', '-s', package_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    check=True, text=True)
            output = result.stdout
            status_line = [line for line in output.split('\n') if line.startswith('Status:')][0]

            if "install ok installed" in status_line:
                logger.info(f"{package_name} package is installed")
                return True
            else:
                logger.info(f"{package_name} package is not installed")
                return False
        except subprocess.CalledProcessError:
            logger.warning(f"Error checking {package_name} package status")
            return False

    @classmethod
    def _get_hotspot_password(cls, usersettings=None):
        if usersettings is None:
            return cls.DEFAULT_HOTSPOT_PASSWORD
        try:
            password = usersettings.get_setting_value("hotspot_password")
        except Exception:
            try:
                password = usersettings.get("hotspot_password")
            except Exception:
                password = None
        if (not password or any(char in str(password) for char in '\r\n\0')
                or not (8 <= len(str(password).encode('utf-8')) <= 63
                        or (len(str(password)) == 64 and all(char in '0123456789abcdefABCDEF' for char in str(password))))):
            return cls.DEFAULT_HOTSPOT_PASSWORD
        return str(password)

    @classmethod
    def create_hotspot_profile(cls, password=None):
        # Check if the 'Hotspot' profile already exists
        hotspot_name = cls.HOTSPOT_CONNECTION_NAME
        hotspot_ssid = cls.HOTSPOT_SSID
        hotspot_iface = cls.HOTSPOT_IFACE
        password = cls._get_hotspot_password({'hotspot_password': password})
        if password is None:
            logger.warning('No valid hotspot password is configured; hotspot startup is disabled')
            return False

        check_profile = subprocess.run(['sudo', 'nmcli', 'connection', 'show', hotspot_name],
                                       capture_output=True, text=True)

        if check_profile.returncode == 0 and hotspot_name in check_profile.stdout:
            logger.info("Hotspot profile already exists. Skipping creation.")
        else:
            logger.info("Creating new Hotspot profile...")
            try:
                subprocess.run([
                    'sudo', 'nmcli', 'connection', 'add', 'type', 'wifi', 'ifname', hotspot_iface,
                    'con-name', hotspot_name, 'autoconnect', 'no', 'ssid', hotspot_ssid
                ], check=True)
            except subprocess.CalledProcessError as e:
                logger.warning(f"An error occurred while creating the Hotspot profile: {e}")
                return False

        try:
            subprocess.run([
                'sudo', 'nmcli', 'connection', 'modify', hotspot_name,
                'connection.autoconnect', 'no',
                'connection.interface-name', hotspot_iface,
                '802-11-wireless.ssid', hotspot_ssid,
                '802-11-wireless.mode', 'ap',
                '802-11-wireless.band', 'bg',
                'ipv4.method', 'shared',
                'ipv6.method', 'ignore',
                'wifi-sec.key-mgmt', 'wpa-psk',
                '802-11-wireless-security.pmf', '1',
                'wifi-sec.psk', password
            ], check=True, capture_output=True, text=True)
            logger.info("Hotspot profile is configured.")
            return True
        except subprocess.CalledProcessError as e:
            logger.warning('An error occurred while configuring the Hotspot profile (exit %s)', e.returncode)
            return False

    @staticmethod
    def change_hotspot_password(new_password):
        logger.info("Changing Hotspot password")
        try:
            # Modify the Hotspot connection with the new password
            subprocess.run([
                'sudo', 'nmcli', 'connection', 'modify', 'Hotspot',
                'wifi-sec.psk', new_password
            ], check=True)

            logger.info("Hotspot password changed successfully.")

            # Restart the hotspot to apply changes
            # First, bring the connection down
            subprocess.run(['sudo', 'nmcli', 'connection', 'down', 'Hotspot'], check=False) # Allow failure if not up
            time.sleep(2) # Give it a moment
            # Then, bring it up again
            subprocess.run(['sudo', 'nmcli', 'connection', 'up', 'Hotspot'], check=True)
            logger.info("Hotspot restarted to apply new password.")
            return True
        except subprocess.CalledProcessError as e:
            logger.warning(f"An error occurred while changing the Hotspot password: {e}")
            return False
        except Exception as e:
            logger.warning(f"An unexpected error occurred while changing hotspot password: {e}")
            return False

    @classmethod
    def enable_hotspot(cls, password=None, force=False):
        logger.info("Enabling Hotspot")
        if not cls.create_hotspot_profile(password):
            return False

        subprocess.run(['sudo', 'nmcli', 'radio', 'wifi', 'on'], check=False)
        subprocess.run(['sudo', 'nmcli', 'device', 'set', cls.HOTSPOT_IFACE, 'managed', 'yes'], check=False)

        if force:
            subprocess.run(['sudo', 'nmcli', 'device', 'disconnect', cls.HOTSPOT_IFACE], check=False)
            time.sleep(2)

        try:
            subprocess.run(['sudo', 'nmcli', 'connection', 'up', cls.HOTSPOT_CONNECTION_NAME], check=True)
            return True
        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to start hotspot: {e}")
            return False

    @staticmethod
    def disable_hotspot():
        logger.info("Disabling Hotspot")
        subprocess.run(['sudo', 'nmcli', 'connection', 'down', 'Hotspot'])

    @staticmethod
    def get_current_connections():
        try:
            with open(os.devnull, 'w') as null_file:
                output = subprocess.check_output(['iwconfig'], text=True, stderr=null_file)

            if "Mode:Master" in output:
                return False, "Running as hotspot", ""

            for line in output.split('\n'):
                if "ESSID:" in line:
                    ssid = line.split("ESSID:")[-1].strip().strip('"')
                    if ssid != "off/any":
                        access_point_line = [line for line in output.split('\n') if "Access Point:" in line]
                        if access_point_line:
                            access_point = access_point_line[0].split("Access Point:")[1].strip()
                            return True, ssid, access_point
                        return False, "Not connected to any Wi-Fi network.", ""
                    return False, "Not connected to any Wi-Fi network.", ""

            return False, "No Wi-Fi interface found.", ""
        except subprocess.CalledProcessError:
            return False, "Error occurred while getting Wi-Fi information.", ""

    def is_hotspot_running(self):
        try:
            result = subprocess.run(
                ['nmcli', 'connection', 'show', '--active'],
                capture_output=True,
                text=True
            )
            return 'Hotspot' in result.stdout
        except Exception as e:
            logger.warning(f"Error checking hotspot status: {str(e)}")
            return False

    def manage_hotspot(self, hotspot, usersettings, midiports, first_run=False, current_time=None):
        if first_run:
            self.create_hotspot_profile(self._get_hotspot_password(usersettings))
            if int(usersettings.get("is_hotspot_active")):
                if not self.is_hotspot_running():
                    logger.info("Hotspot is enabled in settings but not running. Starting hotspot...")
                    self.enable_hotspot(self._get_hotspot_password(usersettings), force=True)
                    time.sleep(5)

                    if self.is_hotspot_running():
                        logger.info("Hotspot started successfully")
                    else:
                        logger.warning("Failed to start hotspot")
                else:
                    logger.info("Hotspot is already running")

        if current_time is None:
            current_time = time.time()
        if not hotspot.last_wifi_check_time:
            hotspot.last_wifi_check_time = current_time

        if (current_time - hotspot.hotspot_script_time) > 60 and (current_time - midiports.last_activity) > 60:
            hotspot.hotspot_script_time = current_time
            if int(usersettings.get("is_hotspot_active")):
                return

            wifi_success, wifi_ssid, _ = self.get_current_connections()

            if not wifi_success:
                hotspot.time_without_wifi += (current_time - hotspot.last_wifi_check_time)
                if hotspot.time_without_wifi > 240:
                    logger.info("No wifi connection. Enabling hotspot")
                    usersettings.change_setting_value("is_hotspot_active", 1)
                    self.enable_hotspot(self._get_hotspot_password(usersettings), force=True)
            else:
                hotspot.time_without_wifi = 0

        hotspot.last_wifi_check_time = current_time

    def connect_to_wifi(self, ssid, password, hotspot, usersettings):
        # A request without an SSID must not take the hotspot down: it could be
        # the only way to reach the device.
        if not isinstance(ssid, str) or not ssid:
            logger.warning("Wi-Fi connection refused: no SSID given")
            return False

        # Disable the hotspot first
        self.disable_hotspot()

        # Use a project-owned name so similarly named SSIDs or existing system
        # profiles (including Hotspot) cannot overwrite one another.
        import hashlib
        password = password or ""
        try:
            digest = hashlib.sha256(ssid.encode("utf-8")).hexdigest()[:24]
            con_name = "PLV-" + digest + ("-wpa" if password else "-open")
            existing = subprocess.run(
                ['sudo', 'nmcli', 'connection', 'show', con_name],
                capture_output=True, text=True, check=False,
            )
            if existing.returncode != 0:
                command = [
                    'sudo', 'nmcli', 'connection', 'add', 'type', 'wifi',
                    'ifname', self.HOTSPOT_IFACE, 'con-name', con_name,
                    'ssid', ssid, 'connection.autoconnect', 'yes',
                ]
                if password:
                    command += ['wifi-sec.key-mgmt', 'wpa-psk', 'wifi-sec.psk', password]
                subprocess.run(command, check=True, capture_output=True, text=True)
            elif password:
                subprocess.run([
                    'sudo', 'nmcli', 'connection', 'modify', con_name,
                    'wifi-sec.key-mgmt', 'wpa-psk', 'wifi-sec.psk', password,
                ], check=True, capture_output=True, text=True)

            result = subprocess.run(
                ['sudo', 'nmcli', 'connection', 'up', con_name],
                capture_output=True, text=True, timeout=45,
            )
            if result.returncode == 0:
                logger.info("Successfully connected to Wi-Fi")
                usersettings.change_setting_value("is_hotspot_active", 0)
                return True
            logger.warning("Failed to activate Wi-Fi profile")
        except subprocess.TimeoutExpired:
            logger.warning("Wi-Fi connection attempt timed out")
        except Exception:
            # CalledProcessError contains the full command, including the PSK.
            logger.warning("Failed to configure or activate Wi-Fi profile")

        usersettings.change_setting_value("is_hotspot_active", 1)
        self.enable_hotspot(self._get_hotspot_password(usersettings), force=True)
        return False

    def disconnect_from_wifi(self, hotspot, usersettings):
        logger.info("Disconnecting from wifi")
        hotspot.hotspot_script_time = time.time()
        usersettings.change_setting_value("is_hotspot_active", 1)
        return self.enable_hotspot(self._get_hotspot_password(usersettings), force=True)

    @staticmethod
    def get_wifi_networks():
        try:
            output = subprocess.check_output(['sudo', 'iwlist', 'wlan0', 'scan'], stderr=subprocess.STDOUT)
            networks = output.decode().split('Cell ')

            def calculate_signal_strength(level):
                # Map the signal level to a percentage (0% to 100%) linearly.
                # -50 dBm or higher -> 100%
                # -90 dBm or lower -> 0%
                if level >= -50:
                    return 100
                elif level <= -90:
                    return 0
                else:
                    return 100 - (100 / 40) * (level + 90)

            wifi_dict = defaultdict(lambda: {'Signal Strength': -float('inf'), 'Signal dBm': -float('inf')})

            for network in networks[1:]:
                wifi_data = {}

                address_line = [line for line in network.split('\n') if 'Address:' in line]
                if address_line:
                    wifi_data['Address'] = address_line[0].split('Address:')[1].strip()

                ssid_line = [line for line in network.split('\n') if 'ESSID:' in line]
                if ssid_line:
                    ssid = ssid_line[0].split('ESSID:')[1].strip('"')
                    wifi_data['ESSID'] = ssid

                freq_line = [line for line in network.split('\n') if 'Frequency:' in line]
                if freq_line:
                    wifi_data['Frequency'] = freq_line[0].split('Frequency:')[1].split(' (')[0]

                signal_line = [line for line in network.split('\n') if 'Signal level=' in line]
                if signal_line:
                    signal_dbm = int(signal_line[0].split('Signal level=')[1].split(' dBm')[0])
                    signal_strength = calculate_signal_strength(signal_dbm)
                    wifi_data['Signal Strength'] = signal_strength
                    wifi_data['Signal dBm'] = signal_dbm

                # Update the network info if this is the strongest signal for this SSID
                if wifi_data['Signal Strength'] > wifi_dict[ssid]['Signal Strength']:
                    wifi_dict[ssid].update(wifi_data)

            # Convert the dictionary to a list
            wifi_list = list(wifi_dict.values())

            # Sort descending by "Signal Strength"
            wifi_list.sort(key=lambda x: x['Signal Strength'], reverse=True)

            return wifi_list
        except subprocess.CalledProcessError as e:
            logger.warning(f"Error while scanning Wi-Fi networks: {e.output}")
            return []

    @staticmethod
    def get_local_address():
        try:
            # Get the hostname
            hostname = socket.gethostname()

            # Get the IP address
            ip_address = socket.gethostbyname(hostname + ".local")

            # Construct the full local address
            local_address = f"{hostname}.local"

            return {
                "success": True,
                "local_address": local_address,
                "ip_address": ip_address
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    @staticmethod
    def change_local_address(new_name):
        new_name = _strip_local_suffix(new_name)
        logger.info("Changing local address to " + new_name)
        # Validate the new name
        if not HOSTNAME_LABEL.fullmatch(new_name):
            raise ValueError("Invalid name. Use only letters, numbers, and hyphens "
                             "(1-63 characters, not starting or ending with a hyphen).")

        try:
            # Change the hostname
            subprocess.run(['sudo', 'hostnamectl', 'set-hostname', new_name], check=True)

            # Update /etc/hosts file
            with open(HOSTS_FILE, 'r') as file:
                hosts_content = file.readlines()

            with open(HOSTS_FILE, 'w') as file:
                for line in hosts_content:
                    if "127.0.1.1" in line:
                        file.write(f"127.0.1.1\t{new_name}\n")
                    else:
                        file.write(line)

            # Restart avahi-daemon to apply changes
            subprocess.run(['sudo', 'systemctl', 'restart', 'avahi-daemon'], check=True)

            # Optionally, restart the networking service
            subprocess.run(['sudo', 'systemctl', 'restart', 'networking'], check=True)

            logger.info(f"Local address successfully changed to {new_name}.local")
            return True

        except subprocess.CalledProcessError as e:
            logger.warning(f"An error occurred while changing the local address: {e}")
            return False
        except IOError as e:
            logger.warning(f"An error occurred while updating the hosts file: {e}")
            return False
        except Exception as e:
            logger.warning(f"An unexpected error occurred: {e}")
            return False

    @staticmethod
    def get_current_timezone():
        """Get the current system timezone."""
        try:
            # Try using timedatectl first (preferred method)
            result = subprocess.run(
                ['timedatectl', 'show', '-p', 'Timezone', '--value'],
                capture_output=True,
                text=True,
                check=True
            )
            timezone = result.stdout.strip()
            if timezone:
                return timezone
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
        
        try:
            # Fallback to reading /etc/timezone
            if os.path.exists('/etc/timezone'):
                with open('/etc/timezone', 'r') as f:
                    timezone = f.read().strip()
                    if timezone:
                        return timezone
        except Exception as e:
            logger.warning(f"Error reading timezone from /etc/timezone: {e}")
        
        # Default fallback
        logger.warning("Could not determine timezone, returning UTC")
        return "UTC"

    @staticmethod
    def get_available_timezones():
        """Get list of available timezones."""
        try:
            result = subprocess.run(
                ['timedatectl', 'list-timezones'],
                capture_output=True,
                text=True,
                check=True
            )
            timezones = [tz.strip() for tz in result.stdout.split('\n') if tz.strip()]
            return timezones
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.warning(f"Error getting timezone list: {e}")
            # Return common timezones as fallback
            return [
                "UTC",
                "America/New_York",
                "America/Chicago",
                "America/Denver",
                "America/Los_Angeles",
                "Europe/London",
                "Europe/Paris",
                "Europe/Berlin",
                "Asia/Tokyo",
                "Asia/Shanghai",
                "Australia/Sydney"
            ]

    @staticmethod
    def set_timezone(timezone):
        """Set the system timezone."""
        try:
            logger.info(f"Setting timezone to {timezone}")
            subprocess.run(
                ['sudo', 'timedatectl', 'set-timezone', timezone],
                check=True
            )
            logger.info(f"Timezone successfully changed to {timezone}")
            return True
        except subprocess.CalledProcessError as e:
            logger.warning(f"Error setting timezone: {e}")
            return False
        except Exception as e:
            logger.warning(f"Unexpected error setting timezone: {e}")
            return False
