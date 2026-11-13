"""Disposable, data-only cache for parsed learning MIDI files.

The historical .p suffix is retained for song rename/delete compatibility.
Old pickle files are cache misses and are never deserialized.
"""

import json
import math
import os
import tempfile
from pathlib import Path

import mido
from mido.midifiles.meta import UnknownMetaMessage

CACHE_VERSION = 1
MAX_CACHE_BYTES = 64 * 1024 * 1024


def _paths(song_name, source_path):
    if (not isinstance(song_name, str) or not song_name or song_name in (".", "..")
            or any(character in song_name for character in ("/", "\\", ":", "\0"))):
        raise OSError("Invalid learning cache song name")
    songs_path = Path("Songs")
    if songs_path.is_symlink():
        raise OSError("Symlinked Songs directory is not a cache boundary")
    songs = songs_path.resolve(strict=True)
    source = Path(source_path).resolve(strict=True)
    if (not source.is_file() or not source.is_relative_to(songs)
            or source != (songs / song_name).resolve(strict=True)):
        raise OSError("Learning cache source is outside its song")
    cache = songs / "cache"
    if cache.is_symlink() or cache.resolve().parent != songs:
        raise OSError("Learning cache directory escapes Songs")
    target = cache / (song_name + ".p")
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise OSError("Learning cache is not a regular file")
    return source, cache, target


def _identity(source):
    stat = source.stat()
    return {"mtime_ns": stat.st_mtime_ns, "size": stat.st_size}


def _integer(value, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("Invalid learning cache integer")
    return value


def _decode_data(data):
    tempo = _integer(data["song_tempo"], 1, 0xFFFFFF)
    ticks = _integer(data["ticks_per_beat"], 1, 0x7FFF)
    records = data["song_tracks"]
    times = data["notes_time"]
    if not isinstance(records, list) or not isinstance(times, list):
        raise TypeError("Invalid learning cache lists")
    messages = []
    for record in records:
        if not isinstance(record, dict) or type(record.get("meta")) is not bool:
            raise ValueError("Invalid learning cache message")
        fields = record["message"]
        if not isinstance(fields, dict) or "skip_checks" in fields:
            raise ValueError("Invalid learning cache MIDI fields")
        _integer(fields["time"], 0, 0x0FFFFFFF)
        if record["meta"] and fields.get("type") == "unknown_meta":
            _integer(fields["type_byte"], 0, 127)
            if not isinstance(fields["data"], (list, tuple)):
                raise ValueError("Invalid unknown meta data")
            for byte in fields["data"]:
                _integer(byte, 0, 255)
            message = UnknownMetaMessage(**fields)
        else:
            message_type = mido.MetaMessage if record["meta"] else mido.Message
            message = message_type.from_dict(fields)
        if set(fields) != set(message.dict()):
            raise ValueError("Unexpected learning cache MIDI fields")
        if message.type == "set_tempo":
            _integer(message.tempo, 1, 0xFFFFFF)
        messages.append(message)
    previous = 0
    for value in times:
        if (type(value) not in (int, float) or not math.isfinite(value)
                or value < previous):
            raise ValueError("Invalid learning cache note timestamp")
        previous = value
    if len(times) != sum(not message.is_meta for message in messages):
        raise ValueError("Learning cache note timestamps do not match messages")
    return {"song_tempo": tempo, "ticks_per_beat": ticks,
            "notes_time": times, "song_tracks": messages}


def load_learning_cache(song_name, source_path):
    """Return validated cached data, or None for any unavailable/stale cache."""
    try:
        source, _, target = _paths(song_name, source_path)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        with os.fdopen(os.open(target, flags), "rb") as handle:
            raw = handle.read(MAX_CACHE_BYTES + 1)
        if len(raw) > MAX_CACHE_BYTES:
            return None
        document = json.loads(raw)
        if (not isinstance(document, dict) or type(document.get("version")) is not int
                or document["version"] != CACHE_VERSION
                or document.get("source") != _identity(source)):
            return None
        return _decode_data(document["data"])
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
        return None


def save_learning_cache(song_name, source_path, cache_data):
    """Atomically write a cache; callers may ignore OSError/ValueError failures."""
    source, cache, target = _paths(song_name, source_path)
    data = {"song_tempo": cache_data["song_tempo"],
            "ticks_per_beat": cache_data["ticks_per_beat"],
            "notes_time": list(cache_data["notes_time"]),
            "song_tracks": [{"meta": message.is_meta, "message": message.dict()}
                            for message in cache_data["song_tracks"]]}
    _decode_data(data)
    document = {"version": CACHE_VERSION, "source": _identity(source), "data": data}
    encoded = json.dumps(document, ensure_ascii=True, allow_nan=False).encode("utf-8")
    if len(encoded) > MAX_CACHE_BYTES:
        raise ValueError("Learning cache exceeds size limit")
    cache.mkdir(exist_ok=True)
    temporary = None
    try:
        descriptor, temporary = tempfile.mkstemp(prefix=".learning-", suffix=".tmp", dir=cache)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            os.unlink(temporary)
