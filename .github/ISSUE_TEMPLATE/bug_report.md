---
name: Bug report
about: Create a report to help us improve
title: ''
labels: bug
assignees: ''

---

**Describe the bug**
What happened, and what did you expect to happen?

**Installation and updates**

- Installation method: this fork's `autoinstall.sh`, manual installation, or a prebuilt image (include its release/version).
- Current revision: output of `git -C /home/Piano-LED-Visualizer rev-parse --short HEAD`, if available.
- How you last updated: the web updater, `scripts/reliable_update.py`, Git, or another method. Include the updater's result if the problem occurred during an update.

**Steps to reproduce**
Describe the steps, how often the problem occurs, and whether it follows boot, reconnecting a device, or changing a setting.

**Environment**

- Raspberry Pi model:
- OS release/codename: paste the output of `cat /etc/os-release`.
- OS architecture: output of `dpkg --print-architecture` (`armhf` or `arm64`).
- Service configuration: paste the output below to identify the actual Python executable and systemd overrides.

```bash
systemctl show visualizer.service -p ExecStart -p FragmentPath -p DropInPaths
```

- Python version: run the executable shown in `ExecStart` with `--version`. This fork's current installer uses `/usr/bin/python3`; use the venv executable if your service uses one.
- LED count, GPIO pin, LCD/HAT model, and relevant custom settings:

**MIDI setup (if relevant)**

- Piano/device model and connection: USB or RTP-MIDI.
- Input and playback port names selected in **Ports Settings**, including whether input is set to **Auto**.
- Computer OS and MIDI software; rtpmidid peer/session names for network MIDI.
- What changes when you disconnect and reconnect the device.

You can also include the output of `aconnect -l` and a screenshot of the web MIDI diagnostics.

**Logs**
Collect the service logs over SSH while the problem is occurring. Include the approximate time of the failure and paste text in a code block.

```bash
systemctl status visualizer.service --no-pager -l
sudo journalctl -b -u visualizer.service --no-pager -n 150
```

For RTP-MIDI problems, also include:

```bash
sudo journalctl -b -u rtpmidid.service --no-pager -n 100
```

These commands inspect the running service. Avoid starting another copy of `visualizer.py` while the service is running, as both copies would access the same hardware and ports. Remove passwords or other private information from logs before posting.

**Additional context**
Add screenshots, relevant configuration changes, or anything else needed to reproduce the problem.
