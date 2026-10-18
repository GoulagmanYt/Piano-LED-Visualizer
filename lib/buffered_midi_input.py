"""Keep ALSA draining in RtMidi's native thread, independently of Python's GIL."""
import sys
import threading

import mido

from lib.alsa_input_buffer import enlarge_input_pools
from lib.log_setup import logger


NATIVE_QUEUE_EVENTS = 32768


class BufferedMidiInput:
    def __init__(self, name, callback, *, virtual=False, native_input=None):
        if native_input is None:
            import rtmidi
            native_input = rtmidi.MidiIn(rtapi=rtmidi.API_LINUX_ALSA, name='RtMidiIn Client',
                                        queue_size_limit=NATIVE_QUEUE_EVENTS)
        self._rt = native_input
        self.name = name
        self.callback = callback
        self.error = None
        self._closed = False
        self._stop = threading.Event()
        self._close_lock = threading.Lock()
        self._thread = threading.Thread(target=self._receive, name='midi-input-drain', daemon=True)
        try:
            self._rt.ignore_types(sysex=False, timing=True, active_sense=True)
            # Resizing ALSA's FIFO clears it. Do this before subscribing to
            # the source, while the new client cannot have received notes.
            try:
                enlarge_input_pools()
            except OSError as error:
                logger.warning('Unable to enlarge ALSA input pool: %s', error)
            if virtual:
                self._rt.open_virtual_port(name)
            else:
                names = self._rt.get_ports()
                if name not in names:
                    raise OSError(f'unknown MIDI input port {name!r}')
                self._rt.open_port(names.index(name))
            # No native Python callback is registered. The ALSA thread can
            # empty the 2,000-event kernel FIFO into C++ storage without GIL.
            self._thread.start()
        except Exception:
            self._rt.close_port()
            self._rt.delete()
            self._closed = True
            raise

    @property
    def closed(self):
        return self._closed or self.error is not None

    def _receive(self):
        try:
            while not self._stop.is_set():
                event = self._rt.get_message()
                if event is None:
                    self._stop.wait(.0005)
                    continue
                try:
                    message = mido.Message.from_bytes(event[0])
                except ValueError:
                    continue
                self.callback(message)
        except Exception as error:
            self.error = error
            logger.exception('MIDI input drain failed: %s', self.name)

    def close(self):
        with self._close_lock:
            if self._closed:
                return
            self._stop.set()
            if self._thread is not threading.current_thread():
                self._thread.join(timeout=2)
                if self._thread.is_alive():
                    raise RuntimeError('MIDI input drain did not stop; refusing concurrent native cleanup')
            self._rt.close_port()
            self._rt.delete()
            self._closed = True


def open_midi_input(name, *, callback, virtual=False):
    backend = mido.backend
    if (sys.platform.startswith('linux')
            and backend.name == 'mido.backends.rtmidi'
            and backend.api in (None, 'LINUX_ALSA')):
        return BufferedMidiInput(name, callback, virtual=virtual)
    return mido.open_input(name, callback=callback, virtual=virtual)
