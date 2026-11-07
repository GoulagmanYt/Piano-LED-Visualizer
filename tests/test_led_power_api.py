import json
from types import SimpleNamespace

import pytest

from webinterface import app_state, webinterface


class PixelSnapshot:
    def getPixels(self):
        return [0xFFFFFF] * 176

    def numPixels(self):
        return 176

    def getBrightness(self):
        return 255


@pytest.fixture
def power_client(monkeypatch):
    values = {}
    menu = SimpleNamespace(last_activity=123, is_idle_animation_running=True)
    settings = SimpleNamespace(get_setting_value=values.get, change_setting_value=values.__setitem__)
    driver = PixelSnapshot()
    monkeypatch.setattr(app_state, 'menu', menu, raising=False)
    monkeypatch.setattr(app_state, 'state_manager', None, raising=False)
    monkeypatch.setattr(app_state, 'usersettings', settings, raising=False)
    monkeypatch.setattr(app_state, 'ledstrip', SimpleNamespace(strip=driver, brightness=12.5), raising=False)
    return SimpleNamespace(client=webinterface.test_client(), values=values, menu=menu, driver=driver)


def test_live_estimate_uses_actual_driver_brightness_without_marking_activity(power_client):
    response = power_client.client.get('/api/get_led_power')
    assert response.status_code == 200
    data = response.get_json()
    assert data['available'] is True
    assert data['led_current_a'] == 10.74
    assert data['led_power_w'] == 53.7
    assert power_client.menu.last_activity == 123
    assert power_client.menu.is_idle_animation_running is True


def test_live_estimate_uses_integer_driver_brightness(power_client, monkeypatch):
    monkeypatch.setattr(power_client.driver, 'getBrightness', lambda: 128)
    data = power_client.client.get('/api/get_led_power').get_json()
    assert data['led_current_a'] == 5.48
    assert data['led_power_w'] == 27.4


@pytest.mark.parametrize('key', ['led_ma_per_channel', 'led_idle_ma', 'led_supply_voltage'])
@pytest.mark.parametrize('value', ['nan', 'inf', '1e309', '-1', 'not-a-number', ''])
def test_invalid_calibration_is_rejected_without_saving(power_client, key, value):
    response = power_client.client.get('/api/change_setting', query_string={'setting_name': key, 'value': value})
    assert response.status_code == 400
    assert response.get_json()['success'] is False
    assert key not in power_client.values


def test_zero_idle_current_is_saved_and_used(power_client):
    response = power_client.client.get('/api/change_setting', query_string={'setting_name': 'led_idle_ma', 'value': '0'})
    assert response.status_code == 200
    assert response.get_json()['success'] is True
    assert float(power_client.values['led_idle_ma']) == 0
    assert power_client.client.get('/api/get_led_power').get_json()['led_current_a'] == 10.56


def test_zero_voltage_is_rejected(power_client):
    response = power_client.client.get('/api/change_setting', query_string={'setting_name': 'led_supply_voltage', 'value': '0'})
    assert response.status_code == 400
    assert 'led_supply_voltage' not in power_client.values


def test_invalid_persisted_calibration_returns_finite_unavailable_json(power_client):
    power_client.values['led_ma_per_channel'] = 'nan'
    response = power_client.client.get('/api/get_led_power')
    data = json.loads(response.get_data(as_text=True), parse_constant=lambda value: pytest.fail('Nonfinite JSON: ' + value))
    assert data['available'] is False
    assert 'led_current_a' not in data


def test_pixel_read_failure_is_unavailable_instead_of_idle_consumption(power_client, monkeypatch):
    def failed_read():
        raise RuntimeError('LED worker unavailable')
    monkeypatch.setattr(power_client.driver, 'getPixels', failed_read)
    data = power_client.client.get('/api/get_led_power').get_json()
    assert data['available'] is False
    assert 'led_current_a' not in data


def test_partial_pixel_snapshot_is_unavailable(power_client, monkeypatch):
    monkeypatch.setattr(power_client.driver, 'getPixels', lambda: [0])
    assert power_client.client.get('/api/get_led_power').get_json()['available'] is False
