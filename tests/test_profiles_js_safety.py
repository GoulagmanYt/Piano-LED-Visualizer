#!/usr/bin/env python3
"""Profile names are free text stored by the server: the UI must never parse
them as HTML (stored XSS). Verified once with jsdom: the old code injected an
<img> element and broke out of the title attribute."""

import re
from pathlib import Path

PROFILES_JS = Path("webinterface/static/js/profiles.js")


def test_profile_names_are_never_assigned_through_innerhtml():
    source = PROFILES_JS.read_text(encoding="utf-8")

    for match in re.finditer(r"innerHTML\s*\+?=", source):
        statement = source[match.start(): source.index(";", match.start())]
        assert "${" not in statement, "interpolated value reaches innerHTML: " + statement[:80]
        assert ".name" not in statement, "profile name reaches innerHTML: " + statement[:80]


def test_selected_profile_label_is_set_as_text():
    source = PROFILES_JS.read_text(encoding="utf-8")

    assert "toggleLabel.textContent = selectedProfile ? selectedProfile.name" in source
    assert "toggleLabel.title = selectedProfile ? selectedProfile.name" in source
