import threading
import time

from lib.async_strip import AsyncPixelStrip


class Backend:
    def __init__(self):
        self.pixels = [0] * 8
        self.frames = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.cleaned = False
        self.fail = False

    def numPixels(self):
        return len(self.pixels)

    def getBrightness(self):
        return 128

    def setBrightness(self, value):
        pass

    def setPixelColor(self, index, color):
        self.pixels[index] = color

    def show(self):
        if self.fail:
            raise RuntimeError('DMA failed')
        self.frames.append(self.pixels.copy())
        self.entered.set()
        assert self.release.wait(1)

    def _cleanup(self):
        self.cleaned = True


def test_transmission_does_not_block_producer_and_close_latches_black():
    backend = Backend()
    strip = AsyncPixelStrip(backend)
    buffers = (id(strip._pixels), id(strip._pending), id(strip._transmit))
    try:
        strip.setPixelColor(0, 123)
        strip.show()
        assert backend.entered.wait(1)
        # Backend is deliberately blocked. Producer must still make progress.
        for n in range(100):
            strip.setPixelColor(0, n)
            strip.show()
        assert buffers == (id(strip._pixels), id(strip._pending), id(strip._transmit))
    finally:
        backend.release.set()
        strip.close()
    assert backend.cleaned
    assert backend.frames[-1] == [0] * 8
    strip.setPixelColor(0, 255)
    strip.show()
    assert strip.getPixels() == [0] * 8
    strip.close()


def test_worker_failure_reaches_supervisor():
    backend = Backend()
    backend.fail = True
    strip = AsyncPixelStrip(backend)
    strip.show()
    strip._thread.join(1)
    try:
        strip.check_health()
    except RuntimeError:
        pass
    else:
        raise AssertionError('worker error hidden')
    backend.fail = False
    backend.release.set()
    strip.close()
    assert backend.cleaned
