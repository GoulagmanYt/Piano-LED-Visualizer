import importlib
import json

import pytest


@pytest.mark.parametrize(
    "pixels,brightness,current,power,maximum",
    [
        ([0] * 176, 255, 0.18, 0.9, 10.74),
        ([0xFFFFFF] * 176, 255, 10.74, 53.7, 10.74),
        ([0xFF0000] * 176, 255, 3.70, 18.5, 10.74),
        ([0xFFFFFF] * 176, 0, 0.18, 0.9, 10.74),
        ([0xFFFFFF] * 176, 128, 5.48, 27.4, 10.74),
        ([], 255, 0.0, 0.0, 0.0),
    ],
)
def test_estimate_matches_hand_calculated_rgb_loads(pixels, brightness, current, power, maximum):
    estimate = importlib.import_module("lib.led_power").estimate_led_power
    result = estimate(tuple(pixels), brightness)
    assert result == {
        "available": True,
        "led_current_a": current,
        "led_power_w": power,
        "led_current_max_a": maximum,
        "led_ma_per_channel": 20.0,
        "led_idle_ma": 1.0,
        "led_supply_voltage": 5.0,
    }
    json.dumps(result, allow_nan=False)


def test_zero_calibration_is_preserved_without_mutating_inputs():
    estimate = importlib.import_module("lib.led_power").estimate_led_power
    pixels = [0xFFFFFF] * 10
    settings = {"led_ma_per_channel": "0", "led_idle_ma": "0", "led_supply_voltage": "12"}
    original = settings.copy()
    result = estimate(pixels, 255, settings)
    assert result["led_current_a"] == 0
    assert result["led_current_max_a"] == 0
    assert result["led_power_w"] == 0
    assert result["led_ma_per_channel"] == 0
    assert result["led_idle_ma"] == 0
    assert result["led_supply_voltage"] == 12
    assert pixels == [0xFFFFFF] * 10
    assert settings == original


@pytest.mark.parametrize("settings", [None, {}, {"led_ma_per_channel": None, "led_idle_ma": "", "led_supply_voltage": None}])
def test_missing_calibration_uses_independent_defaults(settings):
    estimate = importlib.import_module("lib.led_power").estimate_led_power
    assert estimate([0xFFFFFF] * 176, 255, settings)["led_current_a"] == 10.74


def test_partial_calibration_keeps_other_defaults():
    estimate = importlib.import_module("lib.led_power").estimate_led_power
    result = estimate([0xFFFFFF] * 100, 255, {"led_idle_ma": "0"})
    assert result["led_current_a"] == 6.0
    assert result["led_power_w"] == 30.0
    assert result["led_supply_voltage"] == 5.0


@pytest.mark.parametrize("name,value,expected", [
    ("led_ma_per_channel", "0", 0.0),
    ("led_idle_ma", 0, 0.0),
    ("led_supply_voltage", " 12.5 ", 12.5),
])
def test_parse_accepts_valid_calibration(name, value, expected):
    parse = importlib.import_module("lib.led_power").parse_power_setting
    assert parse(name, value) == expected


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "1e999", "-1", "broken", None, "", object()])
@pytest.mark.parametrize("name", ["led_ma_per_channel", "led_idle_ma", "led_supply_voltage"])
def test_parse_rejects_invalid_calibration(name, value):
    parse = importlib.import_module("lib.led_power").parse_power_setting
    with pytest.raises(ValueError):
        parse(name, value)


@pytest.mark.parametrize("name,value", [("led_supply_voltage", "0"), ("unknown", "1")])
def test_parse_rejects_zero_voltage_and_unknown_settings(name, value):
    parse = importlib.import_module("lib.led_power").parse_power_setting
    with pytest.raises(ValueError):
        parse(name, value)


@pytest.mark.parametrize("settings", [
    {"led_idle_ma": "nan"},
    {"led_ma_per_channel": "-1"},
    {"led_supply_voltage": "0"},
    {"led_ma_per_channel": "1e308"},
    {"led_supply_voltage": "1e308"},
])
def test_invalid_or_overflowing_persisted_settings_are_unavailable(settings):
    estimate = importlib.import_module("lib.led_power").estimate_led_power
    with pytest.raises(ValueError):
        estimate([0xFFFFFF] * 176, 255, settings)


@pytest.mark.parametrize("brightness", [-1, 256, 128.5, "128", None, float("nan")])
def test_invalid_driver_brightness_is_rejected(brightness):
    estimate = importlib.import_module("lib.led_power").estimate_led_power
    with pytest.raises(ValueError):
        estimate([0], brightness)


@pytest.mark.parametrize("pixel", [-1, 0x1000000, 1.5, "255", None])
def test_invalid_rgb_pixel_is_rejected(pixel):
    estimate = importlib.import_module("lib.led_power").estimate_led_power
    with pytest.raises(ValueError):
        estimate([pixel], 255)
