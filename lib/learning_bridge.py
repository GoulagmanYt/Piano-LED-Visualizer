"""Opt-in, source-aware Synthesia bridge with fail-closed port ownership."""
import re
import subprocess
import threading
import time

import mido

from lib.buffered_midi_input import open_midi_input
from lib.learning_output import LearningOutput
from lib.learning_session import LearningSession
from lib.log_setup import logger
from lib.midiport_resolver import descriptive_port_name

_ID = re.compile(r'\s(\d+:\d+)$')
_DISABLED_TOKENS = frozenset(('disabled', 'off'))
_INHERIT_TOKENS = frozenset(('', 'none', 'default', 'auto'))
_AUTO_NON_LOCAL_MARKERS = ('midi through', 'rtpmidi', 'rtpmidid', 'oscmidi', 'virmidi', 'client-')
_NETWORK_MARKERS = ('rtpmidi', 'rtpmidid', 'oscmidi')


def _norm_token(value):
    if value is None:
        return ''
    return str(value).strip().lower()


def _is_disabled(value):
    return _norm_token(value) in _DISABLED_TOKENS


def _is_inherit(value):
    return _norm_token(value) in _INHERIT_TOKENS


def _safe_get_setting(settings, key):
    if settings is None:
        return None
    try:
        return settings.get_setting_value(key)
    except Exception:
        return None


def _select_local_hardware_port(available, exclude_names=()):
    """Select a single unambiguous local hardware MIDI port (excluding RTP-MIDI and Midi Through)."""
    excluded_keys = {
        descriptive_port_name(str(name)).lower()
        for name in exclude_names
        if name and not _is_inherit(name) and not _is_disabled(name) and descriptive_port_name(str(name))
    }
    candidates = []
    for port in available:
        desc = descriptive_port_name(port)
        desc_lower = desc.lower()
        port_lower = port.lower()
        if not desc or desc_lower in excluded_keys:
            continue
        if any(marker in desc_lower or marker in port_lower for marker in _AUTO_NON_LOCAL_MARKERS):
            continue
        candidates.append(port)
    return candidates[0] if len(candidates) == 1 else None


def _select_network_port(available, exclude_names=()):
    """Select a single unambiguous RTP-MIDI / network session port when Computer is set to 'auto'."""
    excluded_keys = {
        descriptive_port_name(str(name)).lower()
        for name in exclude_names
        if name and not _is_inherit(name) and not _is_disabled(name) and descriptive_port_name(str(name))
    }
    candidates = []
    for port in available:
        desc = descriptive_port_name(port)
        desc_lower = desc.lower()
        port_lower = port.lower()
        if not desc or desc_lower in excluded_keys:
            continue
        if 'midi through' in desc_lower or 'midi through' in port_lower:
            continue
        if any(marker in desc_lower or marker in port_lower for marker in _NETWORK_MARKERS):
            candidates.append(port)
    return candidates[0] if len(candidates) == 1 else None


def resolve_unique(requested, available):
    """Resolve a requested port name to a single unambiguous available port.

    Fails closed (returns None) if zero or multiple ports match at any tier.
    """
    if not requested:
        return None
    cleaned = str(requested).strip()
    token = cleaned.lower()
    if not cleaned or token in _DISABLED_TOKENS or token in _INHERIT_TOKENS:
        return None

    # Tier 1: Exact full name match
    if cleaned in available:
        return cleaned

    # Tier 2: Exact descriptive name match (strips ALSA client:port numbers)
    key = descriptive_port_name(cleaned)
    if key:
        matches = [item for item in available if descriptive_port_name(item) == key]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            return None

        # Tier 3: Case-insensitive descriptive name match
        key_lower = key.lower()
        ci_matches = [item for item in available if descriptive_port_name(item).lower() == key_lower]
        if len(ci_matches) == 1:
            return ci_matches[0]
        if len(ci_matches) > 1:
            return None

        # Tier 4: Unambiguous substring match on descriptive name or raw port name
        sub_matches = [
            item for item in available
            if key_lower in descriptive_port_name(item).lower() or cleaned.lower() in item.lower()
        ]
        if len(sub_matches) == 1:
            return sub_matches[0]

    return None


def resolve_bridge_endpoints(settings_dict, inputs, outputs):
    """Resolve the 4 bridge endpoints using 2-Role Hybrid Unification and 4-Port overrides.

    Resolution order:
    1. Explicit 4-port settings (`learning_piano_input/output`, `learning_computer_input/output`).
    2. Symmetric pairing within each logical device role (`Piano` In<->Out, `Computer` In<->Out)
       whenever one direction is configured and the counterpart is left on default/auto/empty.
    3. Logical Role Inheritance from Standard settings (`input_port`, `secondary_input_port`,
       `play_port`) when a role is set to `auto` or when standard ports are concretely configured.
    """
    req_pi = settings_dict.get('learning_piano_input')
    req_po = settings_dict.get('learning_piano_output')
    req_ci = settings_dict.get('learning_computer_input')
    req_co = settings_dict.get('learning_computer_output')

    std_in = settings_dict.get('input_port')
    std_sec = settings_dict.get('secondary_input_port')
    std_play = settings_dict.get('play_port')

    explicit_auto_requested = any(
        _norm_token(v) == 'auto' for v in (req_pi, req_po, req_ci, req_co)
    )
    has_concrete_standard_ports = any(
        not _is_inherit(v) and not _is_disabled(v) for v in (std_in, std_sec, std_play)
    )

    # Role 2 (Computer) inheritance from secondary_input_port / play_port / network auto-detect
    if _is_inherit(req_ci) and _is_inherit(req_co):
        if not _is_inherit(std_sec) and not _is_disabled(std_sec):
            req_ci = std_sec
        elif not _is_inherit(std_play) and not _is_disabled(std_play):
            if _is_inherit(std_in) or descriptive_port_name(str(std_play)) != descriptive_port_name(str(std_in)):
                req_co = std_play
        elif _norm_token(req_ci) == 'auto' or _norm_token(req_co) == 'auto':
            auto_net = _select_network_port(inputs, exclude_names=(req_pi, req_po, std_in))
            if auto_net:
                req_ci = auto_net

    # Symmetric pairing for Computer (In <-> Out)
    if not _is_inherit(req_ci) and not _is_disabled(req_ci) and _is_inherit(req_co):
        req_co = req_ci
    elif not _is_inherit(req_co) and not _is_disabled(req_co) and _is_inherit(req_ci):
        req_ci = req_co

    # Role 1 (Piano) inheritance from standard input_port or local USB hardware auto-selection
    if _is_inherit(req_pi) and _is_inherit(req_po):
        if not _is_inherit(std_in) and not _is_disabled(std_in):
            req_pi = std_in
        elif (_norm_token(req_pi) == 'auto' or _norm_token(req_po) == 'auto' or
              (_norm_token(std_in) == 'auto' and (explicit_auto_requested or has_concrete_standard_ports or not _is_inherit(req_ci)))):
            auto_piano = _select_local_hardware_port(inputs, exclude_names=(req_ci, req_co))
            if auto_piano:
                req_pi = auto_piano

    # Symmetric pairing for Piano (In <-> Out)
    if not _is_inherit(req_pi) and not _is_disabled(req_pi) and _is_inherit(req_po):
        req_po = req_pi
    elif not _is_inherit(req_po) and not _is_disabled(req_po) and _is_inherit(req_pi):
        req_pi = req_po

    return (
        resolve_unique(req_pi, inputs),
        resolve_unique(req_po, outputs),
        resolve_unique(req_ci, inputs),
        resolve_unique(req_co, outputs),
    )


def alsa_id(name):
    match = _ID.search(name or '')
    return match.group(1) if match else None


def _find_direct_alsa_links(pi, po, ci, co, aconnect_output):
    """Parse `aconnect -l` output and return direct (source, dest) links between Piano and Computer."""
    links = []
    client = None
    port = None
    for line in aconnect_output.splitlines():
        m = re.match(r"client (\d+):", line)
        if m:
            client, port = m.group(1), None
            continue
        m = re.match(r"\s+(\d+)\s+'", line)
        if m and client is not None:
            port = m.group(1)
            continue
        if client is not None and port is not None and 'Connecting To:' in line:
            source = f'{client}:{port}'
            destinations = re.findall(r'\d+:\d+', line.split('Connecting To:', 1)[1])
            if source == pi and co and co in destinations:
                links.append((pi, co))
            if source == ci and po and po in destinations:
                links.append((ci, po))
    return links


def disconnect_direct_links(piano_input, piano_output, computer_input, computer_output):
    """Surgically remove direct ALSA subscriptions between Piano and Computer endpoints.

    Leaves unrelated ALSA subscriptions intact. Returns list of disconnected (src, dst) pairs.
    """
    pi, po, ci, co = map(alsa_id, (piano_input, piano_output, computer_input, computer_output))
    if not ((pi and co) or (ci and po)):
        return []
    try:
        output = subprocess.run(
            ['aconnect', '-l'], capture_output=True, text=True, check=True, timeout=3
        ).stdout
    except Exception as error:
        logger.debug('Could not inspect ALSA graph for surgical disconnect: %s', error)
        return []

    disconnected = []
    for src, dst in _find_direct_alsa_links(pi, po, ci, co, output):
        try:
            res = subprocess.run(
                ['aconnect', '-d', src, dst], capture_output=True, text=True, check=False, timeout=3
            )
            if res.returncode == 0:
                logger.info('Disconnected direct ALSA link %s -> %s for Learning Bridge', src, dst)
                disconnected.append((src, dst))
            else:
                logger.warning('aconnect -d %s %s exited with %s: %s', src, dst, res.returncode, res.stderr.strip())
        except Exception as error:
            logger.warning('Failed to disconnect direct ALSA link %s -> %s: %s', src, dst, error)
    return disconnected


def verify_no_direct_links(piano_input, piano_output, computer_input, computer_output):
    """Reject existing direct ALSA subscriptions between the two devices.

    Unknown graph/IDs fail closed. Do not delete user's connections implicitly during passive checks.
    """
    ids = list(map(alsa_id, (piano_input, piano_output, computer_input, computer_output)))
    if any(item is None for item in ids):
        raise ValueError('Learning requires identifiable ALSA MIDI ports')
    pi, po, ci, co = ids
    if pi == ci or po == co or pi == co or ci == po:
        raise ValueError('Piano and computer endpoints must be distinct')
    output = subprocess.run(['aconnect', '-l'], capture_output=True, text=True, check=True, timeout=3).stdout
    if _find_direct_alsa_links(pi, po, ci, co, output):
        raise ValueError('Direct piano/computer ALSA connection exists; disconnect it before Learning mode')


class LearningBridge:
    """One generation of four MIDI ports, restarted only after complete cleanup."""
    _SETTING_KEYS = (
        'learning_piano_input',
        'learning_piano_output',
        'learning_computer_input',
        'learning_computer_output',
        'learning_block_control',
        'input_port',
        'secondary_input_port',
        'play_port',
    )

    def __init__(self, queues, settings, *, open_input=open_midi_input, open_output=None,
                 verify_links=verify_no_direct_links, practice_active=None, activity=None):
        self.queues = queues
        self._settings_source = settings
        self._settings = self._read_settings_snapshot(settings)
        self._open_input = open_input
        self._open_output = open_output or mido.open_output
        self._verify_links = verify_links
        self._practice_active = practice_active or (lambda: False)
        self._activity = activity or (lambda: None)
        self._lock = threading.Lock()
        self._inputs = []
        self._outputs = []
        self._session = None
        self._names = None
        self._fault = threading.Event()
        self.status = 'waiting for ports'
        self._closed = False

    @classmethod
    def _read_settings_snapshot(cls, settings):
        return {key: _safe_get_setting(settings, key) for key in cls._SETTING_KEYS}

    @property
    def active_ports(self):
        """Return currently bound (piano_in, piano_out, computer_in, computer_out) tuple or None."""
        return self._names

    def refresh_settings(self, settings=None):
        """Update settings snapshot and trigger clean generation rebuild if endpoints/options changed."""
        source = settings or self._settings_source
        if source is None:
            return
        new_snapshot = self._read_settings_snapshot(source)
        with self._lock:
            if new_snapshot != self._settings:
                self._settings = new_snapshot
                self._fault.set()

    def disconnect_direct_alsa_links(self, inputs=None, outputs=None):
        """Surgically disconnect any direct Piano<->Computer ALSA links for the resolved endpoints."""
        if self._settings_source is not None:
            self.refresh_settings(self._settings_source)
        try:
            avail_in = inputs if inputs is not None else mido.get_input_names()
            avail_out = outputs if outputs is not None else mido.get_output_names()
            names = resolve_bridge_endpoints(self._settings, avail_in, avail_out)
            return disconnect_direct_links(*names)
        except Exception as error:
            logger.debug('Surgical direct ALSA link cleanup skipped: %s', error)
            return []

    def _callback(self, session, source):
        def receive(msg):
            try:
                timestamp = time.perf_counter()
                self._activity()
                if source == 'piano':
                    if session.route_piano(msg, timestamp):
                        self.queues.enqueue_learning_piano(msg, timestamp)
                        if (self._practice_active() and
                                getattr(msg, 'type', None) in ('note_on', 'note_off')):
                            self.queues.enqueue_websocket_publish(msg, timestamp)
                else:
                    session.route_computer(msg, timestamp)
            except Exception:
                logger.exception('Learning MIDI callback failed')
                self._fault.set()
        return receive

    def reset_after_alsa_flush(self):
        """Force generation teardown after an external `aconnect -x` so ports reopen cleanly."""
        with self._lock:
            if self._closed:
                return
            self._fault.set()
            self._stop_generation()
            self.status = 'waiting for ports'

    def reconcile(self, inputs, outputs):
        with self._lock:
            if self._closed:
                return
            names = resolve_bridge_endpoints(self._settings, inputs, outputs)
            healthy = (self._session is not None and not self._fault.is_set() and
                       all(not getattr(p, 'closed', False) for p in self._inputs) and
                       all(p.failure is None for p in self._outputs))
            if healthy and names == self._names:
                try:
                    self._verify_links(*names)
                    return
                except Exception as error:
                    self.status = str(error)
                    self._fault.set()
            if self._session is not None or self._inputs or self._outputs:
                if not self._stop_generation():
                    return
            if any(name is None for name in names):
                self.status = 'waiting for all configured ports'
                return
            try:
                self._verify_links(*names)
                piano_output = LearningOutput(self._open_output(names[1]))
                self._outputs.append(piano_output)
                computer_output = LearningOutput(self._open_output(names[3]))
                self._outputs.append(computer_output)
                session = LearningSession(
                    guide_sink=self.queues.enqueue_guide,
                    piano_sink=piano_output.enqueue,
                    computer_sink=computer_output.enqueue,
                    block_control=str(self._settings['learning_block_control']) != '0',
                )
                self._session = session
                self._inputs.append(self._open_input(names[0], callback=self._callback(session, 'piano')))
                self._inputs.append(self._open_input(names[2], callback=self._callback(session, 'computer')))
                self._names = names
                self._fault.clear()
                self.status = 'connected'
            except Exception as error:
                logger.warning('Learning bridge unavailable: %s', error)
                self.status = str(error)
                self._stop_generation()

    def _stop_generation(self):
        # Stop input callbacks first; never reuse outputs until their worker exits.
        for port in list(self._inputs):
            try:
                port.close()
                self._inputs.remove(port)
            except Exception as error:
                self.status = f'input cleanup failed: {error}'
                return False
        if self._session is not None:
            try:
                self._session.close()
            except Exception as error:
                logger.warning('Learning session cleanup failed: %s', error)
            self._session = None
        for worker in list(self._outputs):
            worker.close(timeout=2)
            if not worker.finished:
                self.status = 'output cleanup timed out; refusing to reopen'
                return False
            self._outputs.remove(worker)
        self._names = None
        return True

    def close(self):
        with self._lock:
            self._closed = True
            return self._stop_generation()
