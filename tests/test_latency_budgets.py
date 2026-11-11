#!/usr/bin/env python3
"""Regression budgets for the real-time paths (see tools/latency_bench.py).

Budgets are generous on purpose: they catch a return to polling or to blocking
the caller, not normal scheduling jitter. Skip with PLV_SKIP_LATENCY=1.
"""

import os
import sys

import pytest

sys.path.append("./")
sys.path.append("../")

from tools import latency_bench

pytestmark = [
    pytest.mark.latency,
    pytest.mark.skipif(
        os.environ.get("PLV_SKIP_LATENCY") == "1", reason="PLV_SKIP_LATENCY=1"
    ),
]


def test_publish_worker_is_woken_by_notes_not_by_polling():
    result = latency_bench.measure_publish_latency()

    assert result["published"] == result["sent"]
    assert result["p95_ms"] < 3.0, result  # polling every 10 ms gave ~9.7 ms
    assert result["mean_ms"] < 1.5, result  # polling every 10 ms gave ~4.8 ms


def test_websocket_broadcast_is_woken_by_appends_not_by_polling():
    result = latency_bench.measure_broadcast_latency(use_wakeup=True)

    assert result["delivered"] == result["sent"]
    assert result["p95_ms"] < 3.0, result  # polling every 10 ms gave ~9.9 ms
    assert result["mean_ms"] < 1.5, result  # polling every 10 ms gave ~5.3 ms


def test_the_benchmark_can_tell_polling_from_wakeup():
    polled = latency_bench.measure_broadcast_latency(use_wakeup=False)
    woken = latency_bench.measure_broadcast_latency(use_wakeup=True)

    assert polled["mean_ms"] > 2 * woken["mean_ms"], (polled, woken)


def test_async_port_change_does_not_wait_for_the_lcd_notice():
    asynchronous = latency_bench.measure_change_port_blocking(async_notice=True)
    synchronous = latency_bench.measure_change_port_blocking(async_notice=False)

    assert synchronous["blocked_ms"] >= 0.8 * synchronous["notice_ms"]
    assert asynchronous["blocked_ms"] < 0.25 * asynchronous["notice_ms"], asynchronous


def test_stop_is_not_held_by_an_lcd_notice():
    result = latency_bench.measure_stop_latency()

    assert result["blocked_ms"] < 0.25 * result["notice_ms"], result
