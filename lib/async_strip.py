"""One hardware owner and reusable latest-frame buffers for WS281x output."""
import threading
import time
import ctypes


def dma_waiter(ws, backend):
    """Call the installed library with the GIL released during DMA completion.

    rpi_ws281x 5.0.0's SWIG wait wrapper holds the GIL. CDLL uses the same
    exported function and pointer, but lets MIDI callbacks and rendering run.
    The worker owns the pointer until close() has joined it.
    """
    library = ctypes.CDLL(ws.__file__)
    wait = library.ws2811_wait
    wait.argtypes = [ctypes.c_void_p]
    wait.restype = ctypes.c_int
    pointer = ctypes.c_void_p(int(backend._leds))

    def wait_for_dma():
        result = wait(pointer)
        if result != 0:
            raise RuntimeError('ws2811_wait failed: %s' % result)

    return wait_for_dma


class AsyncPixelStrip:
    def __init__(self, backend, diagnostics=None, wait_for_dma=None):
        self.backend = backend
        self.diagnostics = diagnostics
        self._wait_for_dma = wait_for_dma
        self._count = backend.numPixels()
        self._pixels = [0] * self._count
        self._note_pixels = [0] * self._count
        self._local = threading.local()
        self._epoch = 0
        self._note_mask_provider = None
        self._protected = set()
        self._background_color = 0
        self._output_enabled = True
        self._animation = None
        self._animation_owner = None
        self._overlays = {}
        self._pending = [0] * self._count
        self._transmit = [0] * self._count
        self._condition = threading.Condition()
        self._hardware_lock = threading.Lock()
        self._dirty = False
        self._closed = False
        self._error = None
        self._submitted = 0.0
        self._brightness = backend.getBrightness()
        self._thread = threading.Thread(target=self._run, name="led-transmit", daemon=True)
        self._thread.start()

    def numPixels(self):
        return self._count

    def setPixelColor(self, index, color):
        if 0 <= index < self._count and not self._closed and self._output_enabled:
            self._updates()[index] = color

    def _updates(self):
        local = self._local
        if getattr(local, "epoch", None) != self._epoch:
            local.epoch = self._epoch
            local.updates = {}
        return local.updates

    def getPixelColor(self, index):
        if not self._closed:
            updates = self._updates()
            if index in updates:
                return updates[index]
        with self._condition:
            return self._pixels[index]

    def getPixels(self):
        with self._condition:
            pixels = self._pixels.copy()
            if not self._closed:
                for index, color in self._updates().items():
                    pixels[index] = color
            return pixels

    def set_note_mask_provider(self, provider):
        """Bind note ownership; called only when a note frame is committed.

        The provider must return indices and must not acquire other locks.
        Animation frames use the last committed mask, never partially edited
        live state from another producer.
        """
        with self._condition:
            self._note_mask_provider = provider

    def animation(self):
        """Return an independent animation framebuffer; close it after use."""
        with self._condition:
            view = _OutputView(self, priority=False)
            self._animation_owner = view
        return view

    def priority_view(self):
        """Return a guide/preview layer above animations and below live notes."""
        with self._condition:
            return _OutputView(self, priority=True)

    def fill_background(self, color, show=True):
        """Change the idle background without erasing committed note ownership."""
        with self._condition:
            if self._closed or not self._output_enabled:
                return
            self._background_color = color
            for index in range(self._count):
                if index not in self._protected:
                    self._note_pixels[index] = color
            if show:
                self._submit()

    def blackout(self, show=True):
        """Explicit force-clear, invalidating all staged frames and old views."""
        with self._condition:
            if self._closed:
                return
            self._blackout_locked(show)

    def _blackout_locked(self, show):
        self._epoch += 1
        self._background_color = 0
        self._note_pixels[:] = [0] * self._count
        self._protected.clear()
        self._overlays.clear()
        self._animation = self._animation_owner = None
        self._pixels[:] = self._note_pixels
        if show:
            self._submit()

    def set_output_enabled(self, enabled):
        """Latch Disabled to black, rejecting producers until explicitly enabled."""
        enabled = bool(enabled)
        with self._condition:
            if self._closed or self._output_enabled == enabled:
                return
            self._output_enabled = enabled
            # Views created while disabled must also be stale after reenable.
            self._blackout_locked(show=not enabled)

    def _submit(self):
        # Caller owns _condition. Nothing here waits for the hardware worker.
        if self._error is not None:
            raise RuntimeError("LED transmission worker failed") from self._error
        animation = self._animation
        self._pixels[:] = animation._published if animation is not None else self._note_pixels
        for overlay in self._overlays.values():
            for index in overlay._published_owned:
                self._pixels[index] = overlay._published[index]
        for index in self._protected:
            self._pixels[index] = self._note_pixels[index]
        self._pending[:] = self._pixels
        self._submitted = time.perf_counter()
        self._dirty = True
        self._condition.notify()

    def _publish_view(self, view):
        with self._condition:
            if (self._closed or not self._output_enabled or view._closed
                    or view._epoch != self._epoch):
                return
            if not view._priority and self._animation_owner is not view:
                return
            view._published[:] = view._frame
            if view._priority:
                view._published_owned = view._owned.copy()
                self._overlays[view] = view
            else:
                self._animation = view
            self._submit()

    def _close_view(self, view):
        with self._condition:
            if view._closed:
                return
            view._closed = True
            changed = self._overlays.pop(view, None) is not None
            if self._animation_owner is view:
                self._animation = self._animation_owner = None
                changed = True
            if changed and not self._closed and self._output_enabled:
                self._submit()

    def setBrightness(self, brightness):
        self._brightness = max(0, min(255, int(brightness)))

    def getBrightness(self):
        return self._brightness

    def configure_gamma(self, ws, gamma):
        with self._hardware_lock:
            if not self._closed:
                ws.ws2811_set_custom_gamma_factor(self.backend._leds, gamma)

    def show(self):
        with self._condition:
            if self._error is not None:
                raise RuntimeError("LED transmission worker failed") from self._error
            if self._closed:
                return
            updates = self._updates()
            if not self._output_enabled:
                updates.clear()
                return
            provider = self._note_mask_provider
            if provider is not None:
                protected = provider()
                for index in self._protected:
                    if index not in protected and index not in updates:
                        self._note_pixels[index] = self._background_color
                self._protected = protected
            else:
                # Standalone adapters have no musical state provider: explicit
                # writes own their pixels, including intentional black.
                self._protected.update(updates)
            for index, color in updates.items():
                self._note_pixels[index] = color
            updates.clear()
            self._submit()

    def _run(self):
        fps_started = time.perf_counter()
        completed_frames = 0
        ready = lambda: self._dirty or self._closed
        transmit = self._transmit
        try:
            while True:
                with self._condition:
                    self._condition.wait_for(ready)
                    if self._closed:
                        return
                    transmit[:] = self._pending
                    submitted = self._submitted
                    brightness = self._brightness
                    self._dirty = False
                started = time.perf_counter()
                with self._hardware_lock:
                    backend = self.backend
                    set_pixel = backend.setPixelColor
                    backend.setBrightness(brightness)
                    for i, color in enumerate(transmit):
                        set_pixel(i, color)
                    backend.show()
                    if self._wait_for_dma is not None:
                        self._wait_for_dma()
                diagnostics = self.diagnostics
                if diagnostics is not None:
                    diagnostics.record_duration("led_transmit_complete", time.perf_counter() - started)
                    diagnostics.record_duration("frame_queue_to_complete", time.perf_counter() - submitted)
                    diagnostics.increment_counter("hardware_frames")
                    completed_frames += 1
                    now = time.perf_counter()
                    if now - fps_started >= 1.0:
                        diagnostics.set_gauge("hardware_fps_last_window", completed_frames / (now - fps_started))
                        completed_frames = 0
                        fps_started = now
        except Exception as error:
            self._error = error

    def check_health(self):
        if self._error is not None:
            raise RuntimeError("LED transmission worker failed") from self._error

    def close(self):
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._condition.notify_all()
        self._thread.join(timeout=2)
        if self._thread.is_alive():
            raise RuntimeError("LED worker did not stop; refusing concurrent DMA cleanup")
        with self._hardware_lock:
            try:
                for i in range(self._count):
                    self._pixels[i] = 0
                    self._note_pixels[i] = 0
                    self.backend.setPixelColor(i, 0)
                self.backend.show()
                # render() can return before the DMA transfer has latched.
                if self._wait_for_dma is not None:
                    self._wait_for_dma()
                else:
                    time.sleep(self._count * 24 / 800000 + 0.003)
            finally:
                self.backend._cleanup()


class _OutputView:
    """One producer's private frame. A view belongs to a single writer thread."""

    def __init__(self, strip, priority):
        self._strip = strip
        self._priority = priority
        self._epoch = strip._epoch
        self._closed = False
        self._frame = [strip._background_color] * strip.numPixels()
        self._published = self._frame.copy()
        self._owned = set()
        self._published_owned = set()

    def numPixels(self):
        return len(self._frame)

    def setPixelColor(self, index, color):
        if 0 <= index < len(self._frame) and not self._closed:
            self._frame[index] = color
            if self._priority:
                self._owned.add(index)

    def clearPixel(self, index):
        """Make a guide pixel transparent, including previously explicit black."""
        self._owned.discard(index)

    def getPixelColor(self, index):
        return self._frame[index]

    def getPixels(self):
        return self._frame.copy()

    def fill_background(self, color, show=True):
        self._frame[:] = [color] * len(self._frame)
        self._owned.clear()
        if show:
            self.show()

    def show(self):
        self._strip._publish_view(self)

    def close(self):
        self._strip._close_view(self)

    def __getattr__(self, name):
        return getattr(self._strip, name)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
