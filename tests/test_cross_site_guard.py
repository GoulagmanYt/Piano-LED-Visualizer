#!/usr/bin/env python3

import io
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.append("./")
sys.path.append("../")

from webinterface import app_state, webinterface
from webinterface.views import is_cross_site_request

DANGEROUS = "/api/change_setting?setting_name=restart_rpi"


@pytest.fixture
def env(monkeypatch):
    platform = MagicMock()
    monkeypatch.setattr(
        app_state, "menu", SimpleNamespace(last_activity=0, is_idle_animation_running=False)
    )
    monkeypatch.setattr(app_state, "state_manager", None)
    monkeypatch.setattr(app_state, "platform", platform)
    for name in ("usersettings", "ledsettings", "ledstrip", "midiports", "learning", "saving"):
        monkeypatch.setattr(app_state, name, MagicMock())
    monkeypatch.delenv("PLV_ALLOW_CROSS_SITE", raising=False)
    return SimpleNamespace(client=webinterface.test_client(), platform=platform)


def _reboot_requested(env, headers):
    env.platform.reset_mock()
    response = env.client.get(DANGEROUS, headers=headers)
    return response, env.platform.reboot.called


def test_cross_site_image_request_cannot_reboot_the_pi(env):
    response, rebooted = _reboot_requested(env, {"Sec-Fetch-Site": "cross-site"})

    assert response.status_code == 403
    assert response.get_json() == {"success": False, "error": "cross-site request blocked"}
    assert rebooted is False


@pytest.mark.parametrize(
    "headers",
    [
        {"Sec-Fetch-Site": "same-origin"},
        {"Sec-Fetch-Site": "none"},
        {"Referer": "http://localhost/songs"},
        {"Origin": "http://localhost"},
        {},
    ],
    ids=["same-origin", "typed-url", "same-host-referer", "same-host-origin", "non-browser"],
)
def test_the_web_ui_and_scripts_still_work(env, headers):
    response, rebooted = _reboot_requested(env, headers)

    assert response.status_code != 403
    assert rebooted is True


@pytest.mark.parametrize(
    "headers",
    [
        {"Referer": "http://evil.example/page"},
        {"Origin": "http://evil.example"},
        {"Origin": "null"},
        {"Sec-Fetch-Site": "same-site", "Origin": "http://localhost:8080"},
    ],
    ids=["referer", "origin", "null-origin", "same-site-other-port"],
)
def test_older_browsers_and_other_ports_are_caught_by_origin_checks(env, headers):
    response, rebooted = _reboot_requested(env, headers)

    assert response.status_code == 403
    assert rebooted is False


def test_cross_site_post_endpoints_are_guarded_too(env, tmp_path, monkeypatch):
    (tmp_path / "Songs").mkdir()
    monkeypatch.chdir(tmp_path)

    response = env.client.post(
        "/upload",
        data={"file": (io.BytesIO(b"MThd"), "evil.mid")},
        content_type="multipart/form-data",
        headers={"Sec-Fetch-Site": "cross-site"},
    )

    assert response.status_code == 403
    assert not (tmp_path / "Songs" / "evil.mid").exists()


def test_pages_stay_reachable_from_links_on_other_sites(env):
    response = env.client.get("/songs", headers={"Sec-Fetch-Site": "cross-site"})

    assert response.status_code == 200


def test_the_guard_can_be_disabled_for_reverse_proxies(env, monkeypatch):
    monkeypatch.setenv("PLV_ALLOW_CROSS_SITE", "1")

    response, rebooted = _reboot_requested(env, {"Sec-Fetch-Site": "cross-site"})

    assert response.status_code != 403
    assert rebooted is True


def test_decision_helper_matches_the_documented_rules():
    def request(headers, host="pi.local"):
        return SimpleNamespace(headers=headers, host=host)

    assert is_cross_site_request(request({"Sec-Fetch-Site": "cross-site"})) is True
    assert is_cross_site_request(request({"Sec-Fetch-Site": "same-origin"})) is False
    assert is_cross_site_request(request({})) is False
    assert is_cross_site_request(request({"Referer": "http://pi.local/home"})) is False
    assert is_cross_site_request(request({"Referer": "http://pi.local:8080/home"})) is True
