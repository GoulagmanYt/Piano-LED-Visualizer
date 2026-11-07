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


def resolve_unique(requested, available):
    if not requested or requested.lower() in ('none', 'default', 'disabled', 'off'):
        return None
    if requested in available:
        return requested
    key = descriptive_port_name(requested)
    matches = [item for item in available if descriptive_port_name(item) == key]
    return matches[0] if len(matches) == 1 else None


def alsa_id(name):
    match = _ID.search(name or '')
    return match.group(1) if match else None


def verify_no_direct_links(piano_input, piano_output, computer_input, computer_output):
    """Reject existing direct ALSA subscriptions between the two devices.

    Unknown graph/IDs fail closed. Do not delete user's connections implicitly.
    """
    ids = list(map(alsa_id, (piano_input, piano_output, computer_input, computer_output)))
    if any(item is None for item in ids):
        raise ValueError('Learning requires identifiable ALSA MIDI ports')
    pi, po, ci, co = ids
    if pi == ci or po == co or pi == co or ci == po:
        raise ValueError('Piano and computer endpoints must be distinct')
    output = subprocess.run(['aconnect', '-l'], capture_output=True, text=True, check=True, timeout=3).stdout
    client = None
    port = None
    for line in output.splitlines():
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
            if (source == pi and co in destinations) or (source == ci and po in destinations):
                raise ValueError('Direct piano/computer ALSA connection exists; disconnect it before Learning mode')


class LearningBridge:
    """One generation of four MIDI ports, restarted only after complete cleanup."""
    def __init__(self, queues, settings, *, open_input=open_midi_input, open_output=None,
                 verify_links=verify_no_direct_links, practice_active=None, activity=None):
        self.queues = queues
        # Configuration is a startup snapshot; changing settings requires a
        # restart, so an active session cannot jump to newly saved endpoints.
        self._settings = {key: settings.get_setting_value(key) for key in (
            'learning_piano_input', 'learning_piano_output',
            'learning_computer_input', 'learning_computer_output', 'learning_block_control')}
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

    def reconcile(self, inputs, outputs):
        with self._lock:
            if self._closed:
                return
            requested = [self._settings[key] for key in (
                'learning_piano_input', 'learning_piano_output',
                'learning_computer_input', 'learning_computer_output')]
            names = (resolve_unique(requested[0], inputs), resolve_unique(requested[1], outputs),
                     resolve_unique(requested[2], inputs), resolve_unique(requested[3], outputs))
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
