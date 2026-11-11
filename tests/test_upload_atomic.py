#!/usr/bin/env python3

import errno
import io
import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from werkzeug.datastructures import FileStorage

sys.path.append("./")
sys.path.append("../")

from webinterface import app_state, webinterface
from webinterface.views import save_upload_atomically


@pytest.fixture
def client(monkeypatch, tmp_path):
    (tmp_path / "Songs").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        app_state, "menu", SimpleNamespace(last_activity=0, is_idle_animation_running=False)
    )
    monkeypatch.setattr(app_state, "state_manager", None)
    return webinterface.test_client()


def _post(client, name, payload):
    return client.post(
        "/upload",
        data={"file": (io.BytesIO(payload), name)},
        content_type="multipart/form-data",
    )


def _songs(tmp_path):
    return sorted(os.listdir(tmp_path / "Songs"))


def test_upload_stores_the_file_and_leaves_no_temporary_file(client, tmp_path):
    response = _post(client, "song.mid", b"MThd-ok")

    assert response.get_json() == {"success": True, "reload_songs": True, "song_name": "song.mid"}
    assert _songs(tmp_path) == ["song.mid"]
    assert (tmp_path / "Songs" / "song.mid").read_bytes() == b"MThd-ok"


def test_failed_write_returns_json_and_leaves_nothing_behind(client, tmp_path, monkeypatch):
    real_save = FileStorage.save

    def disk_full(self, dst, buffer_size=16384):
        Path(dst).write_bytes(b"MThd-partial")
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(FileStorage, "save", disk_full)
    response = _post(client, "song.mid", b"x" * 100)

    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is False
    assert "No space left on device" in body["error"]
    assert body["song_name"] == "song.mid"
    assert _songs(tmp_path) == []

    monkeypatch.setattr(FileStorage, "save", real_save)
    retry = _post(client, "song.mid", b"MThd-ok")
    assert retry.get_json()["success"] is True
    assert (tmp_path / "Songs" / "song.mid").read_bytes() == b"MThd-ok"


def test_existing_song_is_never_overwritten(client, tmp_path):
    (tmp_path / "Songs" / "song.mid").write_bytes(b"original")

    response = _post(client, "song.mid", b"replacement")

    assert response.get_json()["error"] == "file already exists"
    assert (tmp_path / "Songs" / "song.mid").read_bytes() == b"original"
    assert _songs(tmp_path) == ["song.mid"]


def test_save_helper_refuses_to_overwrite_even_if_the_file_appears_late(tmp_path):
    target = tmp_path / "song.mid"
    target.write_bytes(b"winner")

    saved = save_upload_atomically(FileStorage(io.BytesIO(b"late"), filename="song.mid"), target)

    assert saved is False
    assert target.read_bytes() == b"winner"
    assert sorted(os.listdir(tmp_path)) == ["song.mid"]


def test_two_simultaneous_uploads_of_the_same_name_have_exactly_one_winner(tmp_path):
    target = tmp_path / "song.mid"
    payloads = [b"A" * 200_000, b"B" * 200_000]
    barrier = threading.Barrier(2)
    results = []

    def upload(payload):
        storage = FileStorage(io.BytesIO(payload), filename="song.mid")
        barrier.wait()
        results.append(save_upload_atomically(storage, target))

    threads = [threading.Thread(target=upload, args=(payload,)) for payload in payloads]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results) == [False, True]
    assert target.read_bytes() in payloads  # one complete file, never a mix
    assert sorted(os.listdir(tmp_path)) == ["song.mid"]


def test_filesystem_without_hard_links_still_stores_the_file(tmp_path, monkeypatch):
    def no_links(src, dst, *args, **kwargs):
        raise OSError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(os, "link", no_links)
    target = tmp_path / "song.mid"

    saved = save_upload_atomically(FileStorage(io.BytesIO(b"MThd-ok"), filename="song.mid"), target)

    assert saved is True
    assert target.read_bytes() == b"MThd-ok"
    assert sorted(os.listdir(tmp_path)) == ["song.mid"]
