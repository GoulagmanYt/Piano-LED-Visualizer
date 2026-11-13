import json
import os
import pickle
from pathlib import Path

import mido
import pytest
from mido.midifiles.meta import UnknownMetaMessage

from lib.learning_cache import load_learning_cache, save_learning_cache


@pytest.fixture
def song(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "Songs" / "example.mid"
    source.parent.mkdir()
    source.write_bytes(b"example source")
    return source


@pytest.fixture
def data():
    return {
        "song_tempo": 500000, "ticks_per_beat": 480,
        "notes_time": [0, 0.5, 0.5],
        "song_tracks": [mido.MetaMessage("set_tempo", tempo=500000),
                        mido.Message("note_on", note=60),
                        mido.Message("note_off", note=60, time=480),
                        mido.Message("sysex", data=[1, 2]),
                        UnknownMetaMessage(0x7E, data=[1, 255]),
                        mido.MetaMessage("end_of_track")],
    }


def test_json_roundtrip_preserves_midi_messages_and_timing(song, data):
    save_learning_cache(song.name, song, data)
    cached = load_learning_cache(song.name, song)
    assert cached == data
    assert isinstance(cached["song_tracks"][0], mido.MetaMessage)
    assert isinstance(cached["song_tracks"][1], mido.Message)
    document = json.loads((song.parent / "cache" / (song.name + ".p")).read_bytes())
    assert document["version"] == 1


def test_source_replacement_invalidates_cache_even_with_same_size(song, data):
    save_learning_cache(song.name, song, data)
    original = song.stat()
    song.write_bytes(b"changed source")
    os.utime(song, ns=(original.st_atime_ns, original.st_mtime_ns + 1_000_000))
    assert load_learning_cache(song.name, song) is None


def test_legacy_pickle_is_a_miss_and_cannot_execute_code(song):
    marker = song.parent / "executed"

    class Payload:
        def __reduce__(self):
            return Path.write_text, (marker, "executed")

    cache = song.parent / "cache"
    cache.mkdir()
    (cache / (song.name + ".p")).write_bytes(pickle.dumps(Payload()))
    assert load_learning_cache(song.name, song) is None
    assert not marker.exists()


@pytest.mark.parametrize("raw", [b"{broken json", b"[]", b"null", b"\x80\x04pickle"])
def test_corrupt_cache_is_a_miss(song, raw):
    cache = song.parent / "cache"
    cache.mkdir()
    (cache / (song.name + ".p")).write_bytes(raw)
    assert load_learning_cache(song.name, song) is None


@pytest.mark.parametrize("field,value", [
    ("song_tempo", 0), ("ticks_per_beat", -1), ("notes_time", [0, -1, 0]),
    ("notes_time", [0, float("inf"), 0.5]), ("notes_time", [0]),
])
def test_invalid_cached_values_are_rejected(song, data, field, value):
    save_learning_cache(song.name, song, data)
    target = song.parent / "cache" / (song.name + ".p")
    document = json.loads(target.read_bytes())
    document["data"][field] = value
    target.write_text(json.dumps(document))
    assert load_learning_cache(song.name, song) is None


@pytest.mark.parametrize("field,value", [
    ("note", 200), ("time", -1), ("time", 0.5),
    ("skip_checks", True), ("unexpected", 1),
])
def test_invalid_midi_fields_are_rejected(song, data, field, value):
    save_learning_cache(song.name, song, data)
    target = song.parent / "cache" / (song.name + ".p")
    document = json.loads(target.read_bytes())
    document["data"]["song_tracks"][1]["message"][field] = value
    target.write_text(json.dumps(document))
    assert load_learning_cache(song.name, song) is None


@pytest.mark.parametrize("name", ["../escape", "..\\escape", "/escape", "C:escape", ".."])
def test_path_escape_is_rejected(song, data, name):
    assert load_learning_cache(name, song) is None
    with pytest.raises(OSError):
        save_learning_cache(name, song, data)


def test_source_outside_songs_is_rejected(song, data, tmp_path):
    outside = tmp_path / "outside.mid"
    outside.write_bytes(b"outside")
    assert load_learning_cache(song.name, outside) is None
    with pytest.raises(OSError):
        save_learning_cache(song.name, outside, data)


def test_source_directory_is_rejected(song, data):
    song.unlink()
    song.mkdir()
    assert load_learning_cache(song.name, song) is None
    with pytest.raises(OSError):
        save_learning_cache(song.name, song, data)


def make_symlink(link, target, directory=False):
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError as error:
        pytest.skip(f"symlinks unavailable: {error}")


def test_symlinked_cache_directory_cannot_write_outside_songs(song, data, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    make_symlink(song.parent / "cache", outside, directory=True)
    with pytest.raises(OSError):
        save_learning_cache(song.name, song, data)
    assert load_learning_cache(song.name, song) is None
    assert not list(outside.iterdir())


def test_symlinked_cache_file_is_not_read_or_overwritten(song, data, tmp_path):
    outside = tmp_path / "outside.p"
    outside.write_text("untouched")
    cache = song.parent / "cache"
    cache.mkdir()
    make_symlink(cache / (song.name + ".p"), outside)
    assert load_learning_cache(song.name, song) is None
    with pytest.raises(OSError):
        save_learning_cache(song.name, song, data)
    assert outside.read_text() == "untouched"


def test_symlinked_source_outside_songs_is_rejected(song, data, tmp_path):
    outside = tmp_path / "outside.mid"
    outside.write_bytes(b"outside")
    song.unlink()
    make_symlink(song, outside)
    assert load_learning_cache(song.name, song) is None
    with pytest.raises(OSError):
        save_learning_cache(song.name, song, data)


def test_failed_atomic_replace_preserves_previous_cache_and_removes_temp(song, data, monkeypatch):
    save_learning_cache(song.name, song, data)
    target = song.parent / "cache" / (song.name + ".p")
    previous = target.read_bytes()

    def fail_replace(*args):
        raise OSError("disk unavailable")

    monkeypatch.setattr("lib.learning_cache.os.replace", fail_replace)
    with pytest.raises(OSError):
        save_learning_cache(song.name, song, data)
    assert target.read_bytes() == previous
    assert list(target.parent.iterdir()) == [target]
