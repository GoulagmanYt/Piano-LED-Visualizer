"""Pagination helper for the web UI song list.

Kept free of Flask so it can be unit-tested and reused. It stats each song at
most once, ignores files that vanish while the directory is being read, and
filters on the file name only (never on the directory prefix).
"""

import math
import os

DEFAULT_PAGE_LENGTH = 10
MAX_PAGE_LENGTH = 1000


def _positive_int(value, default, maximum=None):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    if number < 1:
        return default
    if maximum is not None:
        number = min(number, maximum)
    return number


def _is_listed_song(name, search):
    if "_#" in name or not name.endswith(".mid"):
        return False
    return not search or search in name.lower()


def list_songs_page(songs_dir, page=None, length=None, sortby=None, search=None):
    """Return one page of songs.

    `page` is 1-based. The result holds `songs` (name -> mtime, in display
    order), `total_songs`, `max_page` and `page_index` (0-based, for templates).
    Sorting keeps the historical behaviour: oldest first by default, newest
    first for "dateAsc", and by name for "nameAsc" / "nameDesc".
    """
    page = _positive_int(page, 1)
    length = _positive_int(length, DEFAULT_PAGE_LENGTH, MAX_PAGE_LENGTH)
    needle = (search or "").lower()
    by_name = sortby in ("nameAsc", "nameDesc")

    try:
        with os.scandir(songs_dir) as entries:
            names = [e.name for e in entries if _is_listed_song(e.name, needle)]
    except OSError:
        names = []

    mtimes = {}
    if by_name:
        names.sort(reverse=(sortby == "nameDesc"))
    else:
        stamped = []
        for name in names:
            try:
                mtimes[name] = os.stat(os.path.join(songs_dir, name)).st_mtime
            except OSError:
                continue  # removed since the directory was read
            stamped.append(name)
        stamped.sort(key=mtimes.__getitem__)
        if sortby == "dateAsc":
            stamped.reverse()
        names = stamped

    total_songs = len(names)
    start = (page - 1) * length
    songs = {}
    for name in names[start:start + length]:
        if name not in mtimes:
            try:
                mtimes[name] = os.stat(os.path.join(songs_dir, name)).st_mtime
            except OSError:
                continue
        songs[name] = mtimes[name]

    return {
        "songs": songs,
        "total_songs": total_songs,
        "max_page": int(math.ceil(total_songs / length)),
        "page_index": page - 1,
    }
