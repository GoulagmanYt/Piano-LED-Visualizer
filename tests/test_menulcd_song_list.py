#!/usr/bin/env python3

import os
import sys
from unittest.mock import MagicMock
from xml.dom import minidom

import pytest

sys.path.append("./")
sys.path.append("../")

from lib.menulcd import MenuLCD

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def menu(tmp_path, monkeypatch):
    menu_xml = os.path.join(REPO_ROOT, "config", "menu.xml")
    instance = object.__new__(MenuLCD)
    instance.DOMTree = minidom.parse(menu_xml)
    instance.scale = lambda x: int(x)
    instance.LCD = MagicMock()
    (tmp_path / "Songs").mkdir()
    monkeypatch.chdir(tmp_path)
    return instance


def _names(menu, tag):
    return [node.getAttribute("text") for node in menu.DOMTree.getElementsByTagName(tag)]


def _touch(tmp_path, *names):
    for name in names:
        (tmp_path / "Songs" / name).write_bytes(b"")


def test_lcd_lists_only_playable_midi_files(menu, tmp_path):
    _touch(
        tmp_path,
        "Nocturne.mid",
        "Etude.MID",
        "score.musicxml",
        "tune.abc",
        "archive.mxl",
        "notes.txt",
    )

    menu.update_songs()

    assert sorted(_names(menu, "Choose_song")) == ["Etude.MID", "Nocturne.mid"]
    assert sorted(_names(menu, "Load_song")) == ["Etude.MID", "Nocturne.mid"]


def test_lcd_never_lists_temporary_upload_files(menu, tmp_path):
    _touch(tmp_path, "song.mid", ".song.mid.0123456789abcdef.part", ".hidden.mid")

    menu.update_songs()

    assert _names(menu, "Choose_song") == ["song.mid"]
    assert _names(menu, "Load_song") == ["song.mid"]


def test_refreshing_the_list_does_not_duplicate_entries(menu, tmp_path):
    _touch(tmp_path, "a.mid", "b.mid")

    menu.update_songs()
    menu.update_songs()

    assert sorted(_names(menu, "Choose_song")) == ["a.mid", "b.mid"]


def test_empty_song_folder_gives_an_empty_menu(menu):
    menu.update_songs()

    assert _names(menu, "Choose_song") == []
    assert _names(menu, "Load_song") == []
