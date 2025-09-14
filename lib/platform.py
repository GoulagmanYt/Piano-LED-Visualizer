import time
import subprocess
from subprocess import call
import os
import filecmp
from shutil import copyfile
from lib.log_setup import logger
import re
import socket
from collections import defaultdict


class Hotspot:
    def __init__(self, hotspot):
        self.hotspot_script_time = 0
        self.time_without_wifi = 0
        self.last_wifi_check_time = 0


class PlatformBase:
    def __getattr__(self, name):
        return self.pass_func

    def pass_func(self, *args, **kwargs):
        pass


class PlatformRasp(PlatformBase):
    @staticmethod
    def check_and_enable_spi():
        try:
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
    def copy_connectall_script():
        if not os.path.exists('/usr/local/bin/connectall.py') or                 filecmp.cmp('/usr/local/bin/connectall.py', 'lib/connectall.py') is not True:
            logger.info("connectall.py script is outdated, updating...")
            copyfile('lib/connectall.py', '/usr/local/bin/connectall.py')
            os.chmod('/usr/local/bin/connectall.py', 0o755)

    def install_midi2abc(self):
        if not self.is_package_installed("abcmidi"):
            logger.info("Installing abcmidi")
            subprocess.call(['sudo', 'apt-get', 'install', 'abcmidi', '-y'])

    @staticmethod
    def update_visualizer():
        call("sudo git reset --hard HEAD", shell=True)
        call("sudo git checkout .", shell=True)
        call("sudo git clean -fdx -e Songs/ -e "
             "config/settings.xml -e config/wpa_disable_ap.conf -e visualizer.log", shell=True)
        call("sudo git clean -fdx Songs/cache", shell=True)
        call("sudo git pull origin master", shell=True)
        call("sudo pip install -r requirements.txt", shell=True)

    @staticmethod
    def shutdown():
        call("sudo /sbin/shutdown -h now", shell=True)

    @staticmethod
    def reboot():
        call("sudo /sbin/reboot now", shell=True)

    # ---------- Try connecting to saved Wi-Fi networks ----------
    def attempt_connect_saved_networks(self, hotspot, usersettings):
        """Try to connect to one of the saved Wi-Fi networks using nmcli.
        Returns (True, ssid) on success, (False, '') otherwise.
        """
        try:
            saved = usersettings.get_saved_wifi_networks()
        except Exception:
            saved = []
        if not saved:
            return (False, '')
        try:
            visible = {n.get('ESSID') for n in self.get_wifi_networks()}
        except Exception:
            visible = set()
        for entry in saved:
            ssid = (entry.get('ssid') or '').strip()
            password = entry.get('password') or ''
            if not ssid or not password:
                continue
            if visible and ssid not in visible:
                continue
            logger.info(f"Trying saved Wi-Fi network: {ssid}")
            try:
                self.disable_hotspot()
                result = subprocess.run(
                    ['sudo', 'nmcli', 'device', 'wifi', 'connect', ssid, 'password', password],
                    capture_output=True, text=True, timeout=25
                )
                if result.returncode == 0:
                    usersettings.change_setting_value("is_hotspot_active", 0)
                    logger.info(f"Connected to saved network {ssid}")
                    return (True, ssid)
                else:
                    logger.warning(f"nmcli failed for {ssid}: {result.stderr.strip()}")
            except subprocess.TimeoutExpired:
                logger.warning(f"nmcli timed out for {ssid}")
            except Exception as e:
                logger.warning(f"Error connecting to {ssid}: {e}")
        return (False, '')

    @staticmethod
    def restart_visualizer():
        call("sudo systemctl restart visualizer", shell=True)

    @staticmethod
    def restart_rtpmidid():
        call("sudo systemctl restart rtpmidid", shell=True)

    @staticmethod
    def is_package_installed(package_name):
        try:
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

    @staticmethod
    def create_hotspot_profile():
        check_profile = subprocess.run(['sudo', 'nmcli', 'connection', 'show', 'Hotspot'],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if check_profile.returncode == 0:
            logger.info("Hotspot profile already exists.")
            return True
        create_hotspot = subprocess.run(['sudo', 'nmcli', 'device', 'wifi', 'hotspot', 'ifname', 'wlan0',
                                         'ssid', 'PianoLED', 'password', '12345678'],
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if create_hotspot.returncode == 0:
            logger.info("Hotspot profile created successfully.")
            return True
        else:
            logger.warning(f"Failed to create Hotspot profile: {create_hotspot.stderr}")
            return False

    @staticmethod
    def change_hotspot_password(password):
        try:
            subprocess.run(['sudo', 'nmcli', 'connection', 'show', 'Hotspot'],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            subprocess.run(['sudo', 'nmcli', 'connection', 'modify', 'Hotspot', 'wifi-sec.key-mgmt', 'wpa-psk'], check=True)
            subprocess.run(['sudo', 'nmcli', 'connection', 'modify', 'Hotspot', 'wifi-sec.psk', password], check=True)
            subprocess.run(['sudo', 'nmcli', 'connection', 'down', 'Hotspot'], check=True)
            subprocess.run(['sudo', 'nmcli', 'connection', 'up', 'Hotspot'], check=True)
            logger.info("Hotspot password successfully changed and applied.")
            return True
        except subprocess.CalledProcessError as e:
            logger.warning(f"An error occurred while changing the Hotspot password: {e}")
            return False
        except Exception as e:
            logger.warning(f"An unexpected error occurred while changing hotspot password: {e}")
            return False

    @staticmethod
    def enable_hotspot():
        logger.info("Enabling Hotspot")
        subprocess.run(['sudo', 'nmcli', 'connection', 'up', 'Hotspot'])

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
                        with open(os.devnull, 'w') as null_file:
                            iw_dev = subprocess.check_output(['iw', 'dev'], text=True, stderr=null_file)
                        interface = re.search(r'Interface\s+(\S+)', iw_dev)
                        interface_name = 'wlan0'
                        if interface:
                            interface_name = interface.group(1)
                        scan_output = subprocess.check_output(['iw', 'dev', interface_name, 'link'], text=True, stderr=null_file)
                        bssid = ""
                        for l in scan_output.split('\n'):
                            if "Connected to" in l:
                                bssid = l.split("Connected to")[-1].strip()
                                break
                        return True, ssid, bssid
            return False, "No Wi-Fi interface found.", ""
        except subprocess.CalledProcessError as e:
            logger.warning(f"Error while checking current connections: {e.output}")
            return False, "", ""
        except Exception as e:
            logger.warning(f"Error while checking current connections: {e}")
            return False, "", ""

    @staticmethod
    def restart_visualizer():
        call("sudo systemctl restart visualizer", shell=True)

    @staticmethod
    def restart_rtpmidid():
        call("sudo systemctl restart rtpmidid", shell=True)

    # ---------- manage_hotspot with saved networks ----------
    def manage_hotspot(self, hotspot, usersettings, midiports, first_run=False):
        if first_run:
            self.create_hotspot_profile()
            if int(usersettings.get("is_hotspot_active")):
                if not self.is_hotspot_running():
                    logger.info("Hotspot is enabled in settings but not running. Starting hotspot...")
                    self.enable_hotspot()
                    time.sleep(5)
                else:
                    logger.info("Hotspot is already running")

        current_time = time.time()
        if not hotspot.last_wifi_check_time:
            hotspot.last_wifi_check_time = current_time

        if (current_time - hotspot.hotspot_script_time) > 60 and (current_time - midiports.last_activity) > 60:
            hotspot.hotspot_script_time = current_time
            if int(usersettings.get("is_hotspot_active")):
                return

            wifi_success, wifi_ssid, _ = self.get_current_connections()

            if not wifi_success:
                ok, used = self.attempt_connect_saved_networks(hotspot, usersettings)
                if ok:
                    hotspot.time_without_wifi = 0
                    return

                hotspot.time_without_wifi += (current_time - hotspot.last_wifi_check_time)
                if hotspot.time_without_wifi > 240:
                    logger.info("No wifi connection. Enabling hotspot")
                    usersettings.change_setting_value("is_hotspot_active", 1)
                    self.enable_hotspot()
                    hotspot.time_without_wifi = 0
            else:
                if self.is_hotspot_running():
                    logger.info("Wifi is connected, disabling hotspot")
                    self.disable_hotspot()
                    usersettings.change_setting_value("is_hotspot_active", 0)
                hotspot.time_without_wifi = 0

        hotspot.last_wifi_check_time = current_time

    def connect_to_wifi(self, ssid, password, hotspot, usersettings):
        self.disable_hotspot()
        try:
            result = subprocess.run(
                ['sudo', 'nmcli', 'device', 'wifi', 'connect', ssid, 'password', password],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                logger.info(f"Successfully connected to {ssid}")
                usersettings.change_setting_value("is_hotspot_active", 0)
                return True
            else:
                logger.warning(f"Failed to connect to {ssid}. Error: {result.stderr}")
                usersettings.change_setting_value("is_hotspot_active", 1)
                self.enable_hotspot()
        except subprocess.TimeoutExpired:
            logger.warning(f"Connection attempt to {ssid} timed out")
            usersettings.change_setting_value("is_hotspot_active", 1)
            self.enable_hotspot()
        except Exception as e:
            logger.warning(f"An error occurred while connecting to {ssid}: {str(e)}")
            usersettings.change_setting_value("is_hotspot_active", 1)
            self.enable_hotspot()

    def disconnect_from_wifi(self, hotspot, usersettings):
        logger.info("Disconnecting from wifi")
        hotspot.hotspot_script_time = time.time()
        self.enable_hotspot()
        usersettings.change_setting_value("is_hotspot_active", 1)

    @staticmethod
    def get_wifi_networks():
        try:
            def calculate_signal_strength(dbm):
                return max(0, min(100, 2 * (dbm + 100)))
            with open(os.devnull, 'w') as null_file:
                scan_output = subprocess.check_output(['sudo', 'iwlist', 'wlan0', 'scan'], text=True, stderr=null_file)
            networks = scan_output.split('Cell ')
            wifi_dict = defaultdict(lambda: {"ESSID": "", "Address": "", "Signal Strength": -100, "Signal dBm": -100})
            for network in networks[1:]:
                essid_line = [line for line in network.split('\n') if 'ESSID:' in line]
                if not essid_line:
                    continue
                essid = essid_line[0].split('ESSID:')[1].strip().strip('"')
                address_line = [line for line in network.split('\n') if 'Address:' in line]
                address = address_line[0].split('Address:')[1].strip() if address_line else ""
                if essid not in wifi_dict:
                    wifi_dict[essid]["ESSID"] = essid
                    wifi_dict[essid]["Address"] = address
                signal_line = [line for line in network.split('\n') if 'Signal level=' in line]
                if signal_line:
                    try:
                        signal_dbm = int(signal_line[0].split('Signal level=')[1].split(' dBm')[0])
                    except Exception:
                        continue
                    signal_strength = calculate_signal_strength(signal_dbm)
                    wifi_data = {
                        "ESSID": essid,
                        "Address": address,
                        "Signal Strength": signal_strength,
                        "Signal dBm": signal_dbm
                    }
                    if wifi_data["Signal Strength"] > wifi_dict[essid]["Signal Strength"]:
                        wifi_dict[essid].update(wifi_data)
            wifi_list = list(wifi_dict.values())
            wifi_list.sort(key=lambda x: x["Signal Strength"], reverse=True)
            return wifi_list
        except subprocess.CalledProcessError as e:
            logger.warning(f"Error while scanning Wi-Fi networks: {e.output}")
            return []

    @staticmethod
    def get_local_address():
        try:
            hostname = socket.gethostname()
            ip_address = socket.gethostbyname(hostname + ".local")
            return f"{hostname}.local ({ip_address})"
        except socket.gaierror as e:
            logger.warning(f"Could not get local address: {e}")
            return "Unknown"
        except Exception as e:
            logger.warning(f"Unexpected error: {e}")
            return "Unknown"

    @staticmethod
    def change_local_address(new_name):
        try:
            with open('/etc/hostname', 'w') as hostname_file:
                hostname_file.write(new_name + '\n')
            with open('/etc/hosts', 'r') as hosts_file:
                hosts_content = hosts_file.read()
            hosts_content = re.sub(r'127\.0\.1\.1\s+\S+', f'127.0.1.1\t{new_name}', hosts_content)
            with open('/etc/hosts', 'w') as hosts_file:
                hosts_file.write(hosts_content)
            subprocess.run(['sudo', 'hostnamectl', 'set-hostname', new_name], check=True)
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

    # This method exists in original codebase; we keep the interface.
    def is_hotspot_running(self):
        try:
            output = subprocess.check_output(['nmcli', '-t', '-f', 'NAME,TYPE,DEVICE', 'connection', 'show', '--active'], text=True)
            for line in output.splitlines():
                if line.startswith('Hotspot:wifi:'):
                    return True
            return False
        except Exception:
            return False
