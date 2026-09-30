from types import SimpleNamespace

from webinterface import app_state, webinterface


def test_general_settings_do_not_expose_hotspot_password(monkeypatch):
    secret = "private-hotspot-password"
    values = {"hotspot_password": secret, "mode": "Fading", "brightness_percent": "75"}
    monkeypatch.setattr(app_state, "usersettings", SimpleNamespace(
        get_setting_value=lambda name: values.get(name, "0")))
    monkeypatch.setattr(app_state, "midiports", SimpleNamespace(
        actual_input_port="piano", actual_play_port="output"))
    monkeypatch.setattr(app_state, "ledsettings", SimpleNamespace())
    monkeypatch.setattr(app_state, "menu", SimpleNamespace(last_activity=0, is_idle_animation_running=False))
    monkeypatch.setattr(app_state, "state_manager", None)

    response = webinterface.test_client().get("/api/get_settings")

    assert response.status_code == 200
    assert response.json["brightness"] == "75"
    assert response.json["input_port"] == "piano"
    assert "hotspot_password" not in response.json
    assert secret not in response.get_data(as_text=True)
