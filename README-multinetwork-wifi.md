# Piano LED Visualizer — Multi‑Network Wi‑Fi Patch

This package contains modified files to enable saving multiple Wi‑Fi networks,
trying them automatically before enabling the hotspot, and a new "Saved Wi‑Fi Networks"
panel in the Network page of the web UI.

## Modified files
- lib/usersettings.py
- lib/platform.py
- webinterface/__init__.py
- webinterface/templates/network.html (injected Saved Wi‑Fi block)
- webinterface/static/js/ui.js (added JS helpers)
- webinterface/static/index.js (loads saved Wi‑Fi list on Network page)

## New file
- webinterface/wifi_api.py

## Install
1. Stop the running service if any:
   sudo systemctl stop visualizer
2. Replace the files in your project tree with the ones from this archive.
3. Start it again:
   sudo systemctl start visualizer

## Notes
- Saved networks are stored in config/settings.xml under <wifi_networks>.
- Passwords are stored in clear text to preserve compatibility with the existing settings mechanism.
