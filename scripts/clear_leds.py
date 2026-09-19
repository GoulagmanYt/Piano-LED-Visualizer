#!/usr/bin/env python3
"""systemd post-stop fallback, run only after the visualizer process has exited."""
import time
from pathlib import Path
from xml.etree import ElementTree
from rpi_ws281x import PixelStrip, ws


def main():
    config = ElementTree.parse(Path(__file__).resolve().parents[1] / 'config/settings.xml')
    count = int(config.findtext('led_count', '195'))
    pin = int(config.findtext('led_pin', '18'))
    channel = int(config.findtext('led_channel', '0'))
    strip = PixelStrip(count, pin, 800000, 10, False, 0, channel, ws.WS2811_STRIP_GRB)
    try:
        strip.begin()
        for index in range(count):
            strip.setPixelColor(index, 0)
        strip.show()
        ws.ws2811_wait(strip._leds)
        print('LED fail-safe: black frame transmitted, DMA wait completed', flush=True)
    finally:
        strip._cleanup()


if __name__ == '__main__':
    main()
