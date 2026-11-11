#!/usr/bin/env python3

import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.append("./")
sys.path.append("../")

import webinterface.views_api as views_api
from webinterface import app_state, webinterface


class _Settings:
    values = {
        "input_port": "default",
        "secondary_input_port": "None",
        "play_port": "None",
        "midi_logging": "0",
        "rtp_autoconnect": "None",
    }

    def get_setting_value(self, name):
        return self.values.get(name)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(
        app_state, "menu", SimpleNamespace(last_activity=0, is_idle_animation_running=False)
    )
    monkeypatch.setattr(app_state, "state_manager", None)
    monkeypatch.setattr(app_state, "usersettings", _Settings())
    monkeypatch.setattr(
        app_state,
        "midiports",
        SimpleNamespace(get_rtp_diagnostics=lambda: {}, get_runtime_diagnostics=lambda: {}),
    )
    monkeypatch.setattr(views_api.mido, "get_input_names", lambda: [])
    monkeypatch.setattr(views_api.mido, "get_output_names", lambda: [])
    monkeypatch.setattr(views_api, "get_rtpmidid_network_diagnostics", lambda _port: {})
    return webinterface.test_client()


@pytest.mark.parametrize(
    "failure",
    [
        FileNotFoundError(2, "No such file or directory: 'aconnect'"),
        subprocess.CalledProcessError(1, ["aconnect", "-i", "-l"]),
        subprocess.TimeoutExpired(["aconnect", "-i", "-l"], 3),
    ],
    ids=["missing", "failing", "stalled"],
)
def test_ports_page_survives_an_unavailable_aconnect(client, failure):
    with patch.object(views_api.subprocess, "check_output", side_effect=failure):
        response = client.get("/api/get_ports")

    assert response.status_code == 200
    body = response.get_json()
    assert isinstance(body, dict) and body


def test_aconnect_call_has_a_timeout():
    with patch.object(views_api.subprocess, "check_output", return_value=b"client 0\n") as run:
        listing = views_api.read_aconnect_listing()

    assert run.call_args.kwargs["timeout"] == 3
    assert listing == str(b"client 0\n")


def test_aconnect_failure_gives_the_same_shape_as_an_empty_listing():
    with patch.object(views_api.subprocess, "check_output", side_effect=FileNotFoundError()):
        assert views_api.read_aconnect_listing() == str(b"")


def test_unknown_sequence_is_a_404_not_a_500(client):
    response = client.get("/api/get_steps_list", query_string={"sequence": "does_not_exist"})

    assert response.status_code == 404
    assert response.get_json() == {"success": False, "error": "Unknown sequence"}


def test_missing_sequence_parameter_is_a_404_not_a_500(client):
    response = client.get("/api/get_steps_list")

    assert response.status_code == 404


def test_known_sequence_still_lists_its_steps(client):
    response = client.get("/api/get_steps_list", query_string={"sequence": "1"})

    assert response.status_code == 200
    body = response.get_json()
    assert "steps_list" in body
