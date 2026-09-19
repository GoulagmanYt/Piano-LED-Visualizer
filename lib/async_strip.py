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
        if 0 <= index < self._count and not self._closed:
            self._pixels[index] = color

    def getPixelColor(self, index):
        return self._pixels[index]

    def getPixels(self):
        # UI-only snapshot; rendering never allocates a frame buffer.
        return self._pixels.copy()

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
            for i in range(self._count):
                self._pending[i] = self._pixels[i]
            self._submitted = time.perf_counter()
            self._dirty = True
            self._condition.notify()

    def _run(self):
        try:
            while True:
                with self._condition:
                    self._condition.wait_for(lambda: self._dirty or self._closed)
                    if self._closed:
                        return
                    for i in range(self._count):
                        self._transmit[i] = self._pending[i]
                    submitted = self._submitted
                    brightness = self._brightness
                    self._dirty = False
                started = time.perf_counter()
                with self._hardware_lock:
                    self.backend.setBrightness(brightness)
                    for i in range(self._count):
                        self.backend.setPixelColor(i, self._transmit[i])
                    self.backend.show()
                    if self._wait_for_dma is not None:
                        self._wait_for_dma()
                diagnostics = self.diagnostics
                if diagnostics is not None:
                    diagnostics.record_duration("led_transmit_complete", time.perf_counter() - started)
                    diagnostics.record_duration("frame_queue_to_complete", time.perf_counter() - submitted)
                    diagnostics.increment_counter("hardware_frames")
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
                    self.backend.setPixelColor(i, 0)
                self.backend.show()
                # render() can return before the DMA transfer has latched.
                if self._wait_for_dma is not None:
                    self._wait_for_dma()
                else:
                    time.sleep(self._count * 24 / 800000 + 0.003)
            finally:
                self.backend._cleanup()
