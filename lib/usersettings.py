from xml.etree import ElementTree as ET
import time
from functools import reduce
from lib.log_setup import logger


class UserSettings:
    def __init__(self, config="config/settings.xml", default_config="config/default_settings.xml"):
        self.cache = {}

        self.CONFIG_FILE = config
        self.DEFAULT_CONFIG_FILE = default_config
        self.pending_changes = False
        self.last_save = 0

        try:
            self.tree = ET.parse(self.CONFIG_FILE)
            self.root = self.tree.getroot()
            self.xml_to_dict(self.cache, self.root)
        except:
            logger.warning("Can't load settings file, restoring defaults")
            self.reset_to_default()

        self.pending_reset = False

        self.copy_missing()
        if self.pending_changes:
            self.save_changes()


    # get setting

    def __getitem__(self, key):
        if isinstance(key, str):
            return self.cache[key]
        elif hasattr(key, '__iter__'):
            # deep get
            return reduce(dict.__getitem__, key, self.cache)

    def get(self, key):
        try:
            return self.__getitem__(key)
        except:
            return None

    def get_setting_value(self, name):
        return self.get(name)

    def get_copy(self):
        return self.cache.copy()


    # set setting

    def __setitem__(self, key, value):
        val = str(value)
        self._xml_set(key, val)

        if isinstance(key, str):
            self.cache[key] = val
        elif hasattr(key, '__iter__'):
            d = reduce(dict.__getitem__, key[:-1], self.cache)
            d[key[-1]] = val

    def set(self, key, value):
        self.__setitem__(key, value)

    def change_setting_value(self, name, value):
        self.set(name, value)



    def get_cms(self, color_mode, key=None):
        if key is None:
            return self.get(("color_mode_settings", color_mode))

        return self.get(("color_mode_settings", color_mode, key))

    def set_cms(self, color_mode, key, value):
        self.set(("color_mode_settings", color_mode, key), value)

    def _xml_set(self, key, value):
        # convert dict key into path query
        if isinstance(key, str):
            find = "./{}".format(key)
            path = [key]
        elif hasattr(key, '__iter__'):
            find = "./" + "/".join(key)
            path = key
        else:
            raise KeyError("Invalid Key Type: {}".format(type(key)))

        elem = self.root.find(find)
        if elem is None:
            # recursively create parents up to leaf
            root_find = './' + '/'.join(path[:-1])
            elem_parent = self.root.find(root_find) if len(path) > 1 else self.root

            if elem_parent is None:
                # Create missing parent chain
                parent = self.root
                for p in path[:-1]:
                    e = parent.find('./' + p)
                    if e is None:
                        e = ET.SubElement(parent, p)
                    parent = e
                elem_parent = parent

            elem = ET.SubElement(elem_parent, path[-1])

        elem.text = value
        self.pending_changes = True

    def save_changes(self):
        if self.pending_changes is True and time.time() - self.last_save > 1:
            logger.warning("Saving user settings")
            self.tree.write(self.CONFIG_FILE, encoding='utf-8', xml_declaration=True)
            self.root = self.tree.getroot()
            self.xml_to_dict(self.cache, self.root)
            self.last_save = time.time()
            self.pending_changes = False

    def save_immediately(self):
        if self.pending_changes:
            self.tree.write(self.CONFIG_FILE, encoding='utf-8', xml_declaration=True)
            self.root = self.tree.getroot()
            self.xml_to_dict(self.cache, self.root)
            self.last_save = time.time()

    def reset_to_default(self):
        self.tree = ET.parse(self.DEFAULT_CONFIG_FILE)
        self.tree.write(self.CONFIG_FILE)
        self.root = self.tree.getroot()
        self.xml_to_dict(self.cache, self.root)
        self.pending_reset = True
        self.last_save = time.time()

    # ---- Saved Wi-Fi networks management ----
    def _ensure_wifi_root(self):
        wifi_root = self.root.find('wifi_networks')
        if wifi_root is None:
            wifi_root = ET.SubElement(self.root, 'wifi_networks')
            self.pending_changes = True
        return wifi_root

    def get_saved_wifi_networks(self):
        nets = []
        wifi_root = self.root.find('wifi_networks')
        if wifi_root is None:
            return nets
        for net in wifi_root.findall('network'):
            ssid = (net.get('ssid') or '').strip()
            pwd = (net.get('password') or '')
            prio = net.get('priority')
            try:
                prio = int(prio) if prio is not None else None
            except:
                prio = None
            nets.append({'ssid': ssid, 'password': pwd, 'priority': prio})
        nets.sort(key=lambda n: (n['priority'] is None, n['priority'] if n['priority'] is not None else 1_000_000))
        return nets

    def add_saved_wifi_network(self, ssid, password, priority=None):
        ssid = str(ssid).strip()
        password = str(password)
        wifi_root = self._ensure_wifi_root()
        for net in wifi_root.findall('network'):
            if (net.get('ssid') or '').strip() == ssid:
                net.set('password', password)
                if priority is not None:
                    net.set('priority', str(priority))
                self.pending_changes = True
                self.save_changes()
                return
        net = ET.SubElement(wifi_root, 'network')
        net.set('ssid', ssid)
        net.set('password', password)
        if priority is not None:
            net.set('priority', str(priority))
        self.pending_changes = True
        self.save_changes()

    def remove_saved_wifi_network(self, ssid):
        ssid = str(ssid).strip()
        wifi_root = self.root.find('wifi_networks')
        if wifi_root is None:
            return False
        removed = False
        for net in list(wifi_root.findall('network')):
            if (net.get('ssid') or '').strip() == ssid:
                wifi_root.remove(net)
                removed = True
        if removed:
            self.pending_changes = True
            self.save_changes()
        return removed

    def xml_to_dict(self, dict, node):
        """Recursively convert xml node into dict
        Assumes xml is simple <tag>text</tag> format, attributes ignored
        """
        for elem in node:
            if len(elem) == 0:
                # No subelements, get text as value
                dict[elem.tag] = elem.text
            else:
                dict[elem.tag] = {}
                self.xml_to_dict(dict[elem.tag], elem)

    def copy_missing(self):
        path = []
        for event, def_elem in ET.iterparse(self.DEFAULT_CONFIG_FILE, events=("start", "end" )):
            if event == 'start':
                path.append(def_elem.tag)

                elem = self.root.find('./' + '/'.join(path[1:]))
                if elem is None:
                    # element might exist but be empty -> create text value if text exists
                    if def_elem.text is not None:
                        if len(path[1:-1]) == 0:
                            parent_elem = self.root
                        else:
                            parent_find = './' + '/'.join(path[1:-1])
                            parent_elem = self.root.find(parent_find)
                        elem = ET.SubElement(parent_elem, def_elem.tag)
                        elem.text = def_elem.text
                        self.pending_changes = True

            elif event == 'end':
                elem = self.root.find('./' + '/'.join(path[1:]))
                if elem is None and len(def_elem) != 0:
                    if len(path[1:-1]) == 0:
                        parent_elem = self.root
                    else:
                        parent_find = './' + '/'.join(path[1:-1])
                        parent_elem = self.root.find(parent_find)
                    parent_elem.insert(0, def_elem)
                    self.pending_changes = True
                path.pop()

        if self.pending_changes:
            self.xml_to_dict(self.cache, self.root)
