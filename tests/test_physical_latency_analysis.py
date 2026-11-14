import pytest

from lib.physical_latency_analysis import analyze_capture


def capture():
    return [{"event_id": str(i), "clock_id": "scope-1", "trigger_ns": str(i * 10_000_000),
             "response_ns": str(i * 10_000_000 + (i + 1) * 1_000_000)} for i in range(3)]


def test_percentiles_preserve_acquisition_identity_and_explicit_measurement_limit():
    result = analyze_capture(capture(), 3)
    assert result["mean_ms"] == result["median_ms"] == 2
    assert result["p95_ms"] == pytest.approx(2.9)
    assert result["p99_ms"] == pytest.approx(2.98)
    assert result["min_ms"] == 1
    assert result["max_ms"] == 3
    assert result["sensor_and_pairing_verified_by_tool"] is False


@pytest.mark.parametrize("mutation", [
    lambda rows: rows.pop(),
    lambda rows: rows[1].update(event_id="0"),
    lambda rows: rows[1].update(event_id="2"),
    lambda rows: rows[1].update(clock_id="scope-2"),
    lambda rows: rows[1].update(clock_id=""),
    lambda rows: rows[1].update(trigger_ns="nan"),
    lambda rows: rows[1].update(trigger_ns=10_000_000.5),
    lambda rows: rows[1].update(trigger_ns=True),
    lambda rows: rows[1].update(response_ns=str(2**64)),
    lambda rows: rows[1].update(response_ns="9000000"),
    lambda rows: rows[1].update(trigger_ns="0"),
    lambda rows: rows[1].pop("response_ns"),
])
def test_invalid_or_partial_capture_is_rejected_without_silent_alignment(mutation):
    rows = capture()
    mutation(rows)
    with pytest.raises(ValueError):
        analyze_capture(rows, 3)


@pytest.mark.parametrize("count", [0, -1, True, 1.2])
def test_invalid_expected_count_is_rejected(count):
    with pytest.raises(ValueError):
        analyze_capture([], count)
