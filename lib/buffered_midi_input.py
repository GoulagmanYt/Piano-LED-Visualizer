"""Keep ALSA draining in RtMidi's native thread, independently of Python's GIL."""
import sys
import threading

import mido

from lib.alsa_input_buffer import enlarge_input_pools
from lib.log_setup import logger
from lib.midi_teardown import MidiTeardown


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
        self._native_port_closed = False
        self._native_deleted = False
        self._thread = threading.Thread(target=self._receive, name='midi-input-drain', daemon=True)
        self._teardown = MidiTeardown(self._cleanup_native, name='midi-input-cleanup')
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
            self._stop.set()
            self._teardown.close()
            raise

    @property
    def closed(self):
        return self._stop.is_set() or self._closed or self.error is not None

    def _receive(self):
        stop_is_set = self._stop.is_set
        stop_wait = self._stop.wait
        get_message = self._rt.get_message
        from_bytes = mido.Message.from_bytes
        try:
            while not stop_is_set():
                event = get_message()
                if stop_is_set():
                    break
                if event is None:
                    stop_wait(.0005)
                    continue
                try:
                    message = from_bytes(event[0])
                except (ValueError, IndexError, TypeError):
                    continue
                self.callback(message)
        except Exception as error:
            self.error = error
            logger.exception('MIDI input drain failed: %s', self.name)
        finally:
            self._teardown.start()

    @property
    def shutdown_status(self):
        return self._teardown.status

    def _cleanup_native(self):
        if self._thread.ident is not None:
            self._thread.join()
        if not self._native_port_closed:
            self._rt.close_port()
            self._native_port_closed = True
        if not self._native_deleted:
            self._rt.delete()
            self._native_deleted = True
        self._closed = True

    def close(self, timeout=2):
        self._stop.set()
        if threading.current_thread() is self._thread:
            self._teardown.start()
            return False
        if not self._teardown.close(timeout):
            raise RuntimeError('MIDI input cleanup incomplete; refusing concurrent native cleanup')
        return True


def open_midi_input(name, *, callback, virtual=False):
    backend = mido.backend
    if (sys.platform.startswith('linux')
            and backend.name == 'mido.backends.rtmidi'
            and backend.api in (None, 'LINUX_ALSA')):
        return BufferedMidiInput(name, callback, virtual=virtual)
    return mido.open_input(name, callback=callback, virtual=virtual)
