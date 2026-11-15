import threading
import time
import ctypes
from types import SimpleNamespace

import pytest

from lib.async_strip import AsyncPixelStrip, pixel_uploader


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


def test_bulk_upload_preserves_rgbw_words_and_does_not_overrun():
    memory = (ctypes.c_uint32 * 5)(0xDEADBEEF, 0, 0, 0, 0xDEADBEEF)
    address = ctypes.addressof(memory) + ctypes.sizeof(ctypes.c_uint32)
    backend = SimpleNamespace(numPixels=lambda: 3, _channel=object())
    ws = SimpleNamespace(ws2811_channel_t_leds_get=lambda channel: address,
                         ws2811_channel_t_count_get=lambda channel: 3)
    upload = pixel_uploader(ws, backend)
    upload([0x00123456, 0x78000000, 0xFFFFFFFF])
    assert list(memory) == [0xDEADBEEF, 0x00123456, 0x78000000, 0xFFFFFFFF, 0xDEADBEEF]
    with pytest.raises(ValueError):
        upload([1, 2, 3, 4])
    assert memory[-1] == 0xDEADBEEF


@pytest.mark.parametrize('address,count', [(0, 8), (123, 7)])
def test_bulk_upload_falls_back_for_invalid_channel(address, count):
    backend = SimpleNamespace(numPixels=lambda: 8, _channel=object())
    ws = SimpleNamespace(ws2811_channel_t_leds_get=lambda channel: address,
                         ws2811_channel_t_count_get=lambda channel: count)
    assert pixel_uploader(ws, backend) is None
    assert pixel_uploader(SimpleNamespace(), backend) is None


def test_worker_bulk_upload_is_serialized_and_records_each_stage():
    from lib.runtime_diagnostics import RuntimeDiagnostics

    backend = Backend()
    backend.release.set()
    diagnostics = RuntimeDiagnostics()
    uploaded = []

    def upload(colors):
        uploaded.append(list(colors))
        backend.pixels[:] = colors

    strip = AsyncPixelStrip(backend, diagnostics=diagnostics,
                           upload_pixels=upload, wait_for_dma=lambda: None)
    try:
        strip.setPixelColor(1, 0x123456)
        strip.show()
        assert backend.entered.wait(1)
    finally:
        strip.close()
    assert uploaded == [[0, 0x123456, 0, 0, 0, 0, 0, 0]]
    assert backend.frames[-1] == [0] * 8
    timings = diagnostics.snapshot()['timings']
    assert {'led_pixel_upload', 'led_render', 'led_dma_wait', 'led_pickup_delay'} <= timings.keys()


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
