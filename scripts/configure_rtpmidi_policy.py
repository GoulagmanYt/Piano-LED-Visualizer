#!/usr/bin/env python3
"""Let PLV own outgoing sessions, retaining mDNS discovery for its UI."""
from pathlib import Path
import re
import shutil
import time


def configure(text):
    # Only change discovery; announcements and hardware export are preserved.
    pattern = r'(?ms)(^\[rtpmidi_discover\]\s*\n)(.*?)(?=^\[|\Z)'
    def update(match):
        body = re.sub(r'^\s*enabled\s*=.*$', 'enabled=false', match[2], flags=re.M)
        if not re.search(r'^enabled=false$', body, re.M):
            body = 'enabled=false\n' + body
        return match[1] + body
    result, count = re.subn(pattern, update, text)
    return result if count else text + '\n[rtpmidi_discover]\nenabled=false\n'


if __name__ == '__main__':
    path = Path('/etc/rtpmidid/default.ini')
    original = path.read_text()
    updated = configure(original)
    if updated != original:
        shutil.copy2(path, str(path) + '.bak-' + time.strftime('%Y%m%d-%H%M%S'))
        path.write_text(updated)
