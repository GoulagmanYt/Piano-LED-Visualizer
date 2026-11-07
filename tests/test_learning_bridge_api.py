from types import SimpleNamespace

import pytest

from webinterface import app_state, webinterface
import webinterface.views_api as api


@pytest.fixture
def scene(monkeypatch):
    values = {}
    settings = SimpleNamespace(get_setting_value=values.get, change_setting_value=values.__setitem__,
                               save_changes=lambda: None)
    monkeypatch.setattr(app_state, 'usersettings', settings)
    monkeypatch.setattr(app_state, 'menu', SimpleNamespace(last_activity=0, is_idle_animation_running=False))
    monkeypatch.setattr(app_state, 'state_manager', None)
    monkeypatch.setattr(app_state, 'midiports', SimpleNamespace(learning_bridge=None, learning_bridge_enabled=False))
    monkeypatch.setattr(api.mido, 'get_input_names', lambda: ['Piano:Keys 20:0', 'PC:Midi 30:0'])
    monkeypatch.setattr(api.mido, 'get_output_names', lambda: ['Piano:Keys 20:0', 'PC:Midi 30:0'])
    ports = dict(learning_piano_input='Piano:Keys 20:0', learning_piano_output='Piano:Keys 20:0',
                 learning_computer_input='PC:Midi 30:0', learning_computer_output='PC:Midi 30:0')
    return SimpleNamespace(client=webinterface.test_client(), values=values, ports=ports)


def test_save_valid_configuration_requires_restart(scene):
    response = scene.client.post('/api/learning_bridge', json={
        'mode': 'learning', 'ports': scene.ports, 'block_control': True})
    assert response.status_code == 200 and response.json['restart_required']
    assert scene.values['midi_bridge_mode'] == 'learning'
    assert scene.values['learning_computer_input'] == 'PC:Midi 30:0'
    assert scene.client.get('/api/learning_bridge').json['active'] is False


def test_invalid_endpoint_is_rejected_without_partial_setting_changes(scene):
    scene.ports['learning_computer_input'] = scene.ports['learning_piano_input']
    response = scene.client.post('/api/learning_bridge', json={
        'mode': 'learning', 'ports': scene.ports, 'block_control': True})
    assert response.status_code == 400
    assert scene.values == {}


def test_disconnected_port_cannot_be_activated(scene):
    scene.ports['learning_computer_output'] = 'Absent:Midi 40:0'
    response = scene.client.post('/api/learning_bridge', json={
        'mode': 'learning', 'ports': scene.ports, 'block_control': True})
    assert response.status_code == 400
    assert scene.values == {}


def test_bridge_can_be_disabled_while_ports_are_offline(scene):
    scene.ports['learning_computer_output'] = 'Absent:Midi 40:0'
    response = scene.client.post('/api/learning_bridge', json={
        'mode': 'off', 'ports': scene.ports, 'block_control': True})
    assert response.status_code == 200
    assert scene.values['midi_bridge_mode'] == 'off'


@pytest.mark.parametrize('action', ['connect_ports', 'disconnect_ports'])
def test_legacy_global_mesh_actions_are_blocked_when_bridge_is_running(scene, monkeypatch, action):
    monkeypatch.setattr(app_state, 'midiports', SimpleNamespace(learning_bridge_enabled=True))
    response = scene.client.get('/api/change_setting', query_string={'setting_name': action, 'value': '0'})
    assert response.status_code == 409
