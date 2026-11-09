#!/usr/bin/env python3

import os
import re
import sys

sys.path.append("./")
sys.path.append("../")

from lib.song_listing import list_songs_page
from webinterface import app_state, webinterface


def _make_songs(folder, names, start_mtime=1_700_000_000):
    for index, name in enumerate(names):
        path = folder / name
        path.write_text("", encoding="utf-8")
        os.utime(path, (start_mtime + index, start_mtime + index))


def test_search_only_matches_file_names_not_the_folder_prefix(tmp_path):
    _make_songs(tmp_path, ["alpha.mid", "beta.mid", "gamma.mid"])

    result = list_songs_page(str(tmp_path), 1, 10, "nameAsc", "song")

    assert result["total_songs"] == 0
    assert result["max_page"] == 0
    assert result["songs"] == {}


def test_total_and_max_page_follow_the_filtered_list(tmp_path):
    _make_songs(tmp_path, ["alpha.mid", "alpine.mid", "beta.mid"])

    result = list_songs_page(str(tmp_path), 1, 1, "nameAsc", "ALP")

    assert result["total_songs"] == 2
    assert result["max_page"] == 2
    assert list(result["songs"]) == ["alpha.mid"]


def test_only_plain_mid_files_are_listed(tmp_path):
    _make_songs(
        tmp_path,
        ["a.mid", "a.musicxml", "a_#ff0000.mid", "notes.txt", "b.mid"],
    )

    result = list_songs_page(str(tmp_path), 1, 10, "nameAsc", "")

    assert list(result["songs"]) == ["a.mid", "b.mid"]
    assert result["total_songs"] == 2


def test_sort_orders_are_preserved(tmp_path):
    _make_songs(tmp_path, ["c.mid", "a.mid", "b.mid"])  # c oldest, b newest

    def names(sortby):
        return list(list_songs_page(str(tmp_path), 1, 10, sortby, "")["songs"])

    assert names("nameAsc") == ["a.mid", "b.mid", "c.mid"]
    assert names("nameDesc") == ["c.mid", "b.mid", "a.mid"]
    assert names("dateDesc") == ["c.mid", "a.mid", "b.mid"]
    assert names("dateAsc") == ["b.mid", "a.mid", "c.mid"]
    assert names(None) == ["c.mid", "a.mid", "b.mid"]


def test_pagination_returns_the_requested_slice_with_mtimes(tmp_path):
    _make_songs(tmp_path, [f"s{i}.mid" for i in range(5)])

    result = list_songs_page(str(tmp_path), 2, 2, "nameAsc", "")

    assert list(result["songs"]) == ["s2.mid", "s3.mid"]
    assert result["page_index"] == 1
    assert result["max_page"] == 3
    assert all(isinstance(mtime, float) for mtime in result["songs"].values())


def test_malformed_paging_values_fall_back_to_safe_defaults(tmp_path):
    _make_songs(tmp_path, ["a.mid", "b.mid"])

    for page, length in ((None, None), ("x", "0"), ("-3", "-1"), ("0", "abc")):
        result = list_songs_page(str(tmp_path), page, length, None, None)
        assert result["page_index"] == 0
        assert result["total_songs"] == 2
        assert len(result["songs"]) == 2


def test_missing_folder_gives_an_empty_page(tmp_path):
    result = list_songs_page(str(tmp_path / "nope"), 1, 10, "nameAsc", "")

    assert result == {"songs": {}, "total_songs": 0, "max_page": 0, "page_index": 0}


def test_song_removed_while_listing_is_skipped(tmp_path, monkeypatch):
    _make_songs(tmp_path, ["a.mid", "b.mid", "c.mid"])
    real_stat = os.stat

    def flaky_stat(path, *args, **kwargs):
        if str(path).endswith("b.mid"):
            raise FileNotFoundError(path)
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr("lib.song_listing.os.stat", flaky_stat)

    for sortby in ("dateDesc", "nameAsc"):
        result = list_songs_page(str(tmp_path), 1, 10, sortby, "")
        assert "b.mid" not in result["songs"]
        assert {"a.mid", "c.mid"} <= set(result["songs"])


class _DummyMenu:
    last_activity = 0
    is_idle_animation_running = False


def _client(monkeypatch, tmp_path):
    (tmp_path / "Songs").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(app_state, "menu", _DummyMenu())
    monkeypatch.setattr(app_state, "state_manager", None)
    return webinterface.test_client()


def test_get_songs_endpoint_survives_missing_or_zero_parameters(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    _make_songs(tmp_path / "Songs", ["alpha.mid"])

    for query in ("", "length=10", "page=1&length=0", "page=abc&length=xyz"):
        response = client.get("/api/get_songs", query_string=query)
        assert response.status_code == 200, query
        assert "alpha.mid" in response.get_data(as_text=True)


def test_get_songs_endpoint_reports_filtered_total(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    _make_songs(tmp_path / "Songs", ["alpha.mid", "beta.mid", "gamma.mid"])

    response = client.get(
        "/api/get_songs",
        query_string={"page": 1, "length": 1, "sortby": "nameAsc", "search": "song"},
    )

    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert re.search(r'font-semibold">0</span>', html)


def test_song_search_is_url_encoded_by_the_web_ui():
    """A raw '&', '+' or '#' in the search box truncated or altered the query."""
    from pathlib import Path

    source = Path("webinterface/static/js/ui.js").read_text(encoding="utf-8")

    assert '"&search=" + encodeURIComponent(search)' in source
    assert '"&search=" + search,' not in source
