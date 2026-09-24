from __future__ import annotations

import json
import logging
import re
import subprocess
import threading
from functools import wraps

logger = logging.getLogger("my_app")

_session_lock = threading.RLock()


def _serialized(func):
    @wraps(func)
    def call(*args, **kwargs):
        with _session_lock:
            return func(*args, **kwargs)
    return call


_TRAILING_ALSA_ID_RE = re.compile(r"\s+\d+:\d+$")


def _default_diagnostics(error_reason=None):
    return {
        "play_network_ready": None,
        "rtpmidi_peer_status": None,
        "rtpmidi_remote_host": None,
        "rtpmidi_error_reason": error_reason,
    }


def _session_name_from_play_port(play_port):
    if not play_port or not str(play_port).startswith("rtpmidid:"):
        return None
    name = str(play_port).split(":", 1)[1]
    name = _TRAILING_ALSA_ID_RE.sub("", name).strip()
    return name or None


def _extract_result(status_payload):
    if not isinstance(status_payload, dict):
        return {}
    result = status_payload.get("result", status_payload)
    return result if isinstance(result, dict) else {}


def _remote_host_from_announcement(result, session_name):
    mdns = result.get("mdns") if isinstance(result, dict) else {}
    announcements = mdns.get("remote_announcements", []) if isinstance(mdns, dict) else []
    for announcement in announcements:
        if announcement.get("name") == session_name:
            hostname = announcement.get("hostname")
            port = announcement.get("port")
            if hostname and port:
                return f"{hostname}:{port}"
            return hostname or None
    return None


def _remote_host_from_peer(peer):
    remote = (peer.get("peer") or {}).get("remote") or {}
    hostname = remote.get("hostname")
    port = remote.get("port")
    if hostname and hostname != "null" and port:
        return f"{hostname}:{port}"
    return None


def _peer_is_ready(peer):
    peer_info = peer.get("peer") or {}
    remote = peer_info.get("remote") or {}
    status = str(peer_info.get("status", "")).upper()
    remote_name = str(remote.get("name") or "").strip()
    remote_ssrc = int(remote.get("ssrc") or 0)
    sent = int((peer.get("stats") or {}).get("sent") or 0)

    if status in {"CONNECTED", "ESTABLISHED", "2"}:
        return True
    if status in {"0", "", "DISCONNECTED", "CONNECTING"}:
        return False
    return bool(remote_name and remote_ssrc and sent >= 0)


def parse_rtpmidid_status(status_payload, play_port=None):
    session_name = _session_name_from_play_port(play_port)
    if not session_name:
        return _default_diagnostics()

    result = _extract_result(status_payload)
    router = result.get("router", []) if isinstance(result, dict) else []
    peers_by_id = {peer.get("id"): peer for peer in router if isinstance(peer, dict)}
    remote_host = _remote_host_from_announcement(result, session_name)

    local_listener = None
    for peer in router:
        if not isinstance(peer, dict):
            continue
        if peer.get("type") != "local_alsa_listener_t":
            continue
        if session_name in str(peer.get("name") or ""):
            local_listener = peer
            break

    if local_listener is None:
        return {
            "play_network_ready": False,
            "rtpmidi_peer_status": None,
            "rtpmidi_remote_host": remote_host,
            "rtpmidi_error_reason": f"{session_name} is not connected to rtpmidid",
        }

    network_peer = None
    for peer_id in local_listener.get("send_to", []) or []:
        candidate = peers_by_id.get(peer_id)
        if candidate and str(candidate.get("type", "")).startswith("network_rtpmidi"):
            network_peer = candidate
            break

    if network_peer is None:
        return {
            "play_network_ready": False,
            "rtpmidi_peer_status": local_listener.get("status"),
            "rtpmidi_remote_host": remote_host,
            "rtpmidi_error_reason": f"{session_name} has no RTP network peer",
        }

    peer_info = network_peer.get("peer") or {}
    peer_status = peer_info.get("status")
    remote_host = _remote_host_from_peer(network_peer) or remote_host
    ready = _peer_is_ready(network_peer)
    error_reason = None
    if not ready:
        error_reason = (
            f"{session_name} ALSA playport is open but the RTP network session is not connected"
        )

    return {
        "play_network_ready": ready,
        "rtpmidi_peer_status": peer_status,
        "rtpmidi_remote_host": remote_host,
        "rtpmidi_error_reason": error_reason,
    }


def parse_rtpmidid_cli_output(output):
    text = output.decode("utf-8", errors="replace") if isinstance(output, bytes) else str(output)
    text = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(">>>"))
    start = text.find("{")
    if start < 0:
        raise ValueError("rtpmidid-cli did not return JSON")
    return json.loads(text[start:])


def get_rtpmidid_network_diagnostics(play_port, *, timeout=1.5):
    try:
        output = subprocess.check_output(
            ["rtpmidid-cli", "status"],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )
        return parse_rtpmidid_status(parse_rtpmidid_cli_output(output), play_port=play_port)
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError) as exc:
        return _default_diagnostics(f"Unable to read rtpmidid status: {exc}")


def get_rtpmidi_peers(*, timeout=2.0):
    """Query rtpmidid for discovered and connected RTP MIDI peers."""
    try:
        output = subprocess.check_output(
            ["rtpmidid-cli", "status"],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )
        payload = parse_rtpmidid_cli_output(output)
        result = _extract_result(payload)
        
        # Discovered peers via mDNS/Avahi
        mdns = result.get("mdns") or {}
        remote_announcements = mdns.get("remote_announcements", []) or []
        discovered = []
        for announcement in remote_announcements:
            if isinstance(announcement, dict):
                discovered.append({
                    "name": announcement.get("name") or "Unknown",
                    "hostname": announcement.get("hostname") or "",
                    "port": int(announcement.get("port") or 5004),
                })

        # Connected or configured router peers
        router = result.get("router") or []
        routed_ids = {pid for p in router if isinstance(p, dict) for pid in (p.get("send_to") or [])}
        connected = []
        seen_ids = set()

        for peer in router:
            if not isinstance(peer, dict):
                continue
            peer_type = peer.get("type")
            peer_id = peer.get("id")

            if peer_type == "network_rtpmidi_client_t":
                peer_info = peer.get("peer") or {}
                remote = peer_info.get("remote") or {}
                latency = peer_info.get("latency_ms") or {}
                connected.append({
                    "id": peer_id,
                    "name": peer.get("name") or remote.get("name") or "Unnamed",
                    "hostname": remote.get("hostname") or "",
                    "port": int(remote.get("port") or 5004),
                    "status": str(peer_info.get("status", "connected")),
                    "latency_ms": latency.get("average"),
                    "kind": "client",
                    "orphan": not peer.get("send_to") and peer_id not in routed_ids,
                })
                if peer_id is not None:
                    seen_ids.add(peer_id)

            elif peer_type == "local_alsa_listener_t" and peer.get("endpoints"):
                # Outgoing configured session / waiting session
                for ep in peer.get("endpoints", []):
                    if isinstance(ep, dict):
                        raw_name = (peer.get("name") or "Remote Peer").replace("[WATING]", "").replace("<->", "").strip()
                        connected.append({
                            "id": peer_id,
                            "name": raw_name or "Remote Peer",
                            "hostname": ep.get("hostname") or "",
                            "port": int(ep.get("port") or 5004),
                            "status": str(peer.get("status", "WAITING")),
                            "latency_ms": None,
                            "kind": "listener",
                        })
                        if peer_id is not None:
                            seen_ids.add(peer_id)

            # Check for incoming connected peers on listeners
            for inc in peer.get("peers", []):
                if isinstance(inc, dict):
                    inc_id = inc.get("id") or peer_id
                    if inc_id in seen_ids:
                        continue
                    remote = inc.get("remote") or {}
                    latency = inc.get("latency_ms") or {}
                    connected.append({
                        "id": inc_id,
                        "name": inc.get("name") or remote.get("name") or peer.get("name") or "Incoming Peer",
                        "hostname": remote.get("hostname") or "",
                        "port": int(remote.get("port") or 5004),
                        "status": str(inc.get("status", "connected")),
                        "latency_ms": latency.get("average"),
                    })
                    if inc_id is not None:
                        seen_ids.add(inc_id)

        return {
            "success": True,
            "daemon_running": True,
            "discovered_peers": discovered,
            "connected_peers": connected,
        }
    except Exception as exc:
        return {
            "success": False,
            "daemon_running": False,
            "error": str(exc),
            "discovered_peers": [],
            "connected_peers": [],
        }


@_serialized
def connect_rtpmidi_peer(hostname: str, port: int = 5004, name: str | None = None, *, timeout=3.0):
    """Connect to a remote RTP MIDI peer via rtpmidid-cli."""
    if not hostname:
        return {"success": False, "error": "Hostname or IP address is required"}
    
    clean_host = str(hostname).strip()
    try:
        clean_port = int(port or 5004)
    except (ValueError, TypeError):
        return {"success": False, "error": "Invalid RTP MIDI port"}
    if not clean_host or not 1 <= clean_port <= 65535:
        return {"success": False, "error": "Invalid RTP MIDI endpoint"}

    # Check if this peer is already connected or has a stale listener to prevent duplicate ALSA ports
    try:
        current_peers = get_rtpmidi_peers(timeout=1.5)
        matches = []
        for cp in current_peers.get("connected_peers", []):
            same_name = bool(name and (cp.get("name") == name or str(name).lower() in (cp.get("name") or "").lower()))
            same_host = cp.get("hostname") == clean_host
            if (same_name or same_host) and cp.get("port") == clean_port:
                if cp.get("orphan"):
                    disconnect_rtpmidi_peer(cp["id"], timeout=1.5)
                else:
                    matches.append(cp)
        if matches:
            # A waiting listener owns the daemon's retry state. Do not replace
            # it every monitor tick, or a slow peer can never finish connecting.
            return {"success": True, "result": ["already_configured"]}
    except Exception:
        pass

    cmd = ["rtpmidid-cli", "connect", f"hostname={clean_host}", f"port={clean_port}"]
    if name:
        cmd.append(f"name={str(name).strip()}")

    try:
        output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, timeout=timeout)
        parsed = parse_rtpmidid_cli_output(output)
        if "error" in parsed and parsed["error"]:
            return {"success": False, "error": str(parsed["error"])}
        return {"success": True, "result": parsed.get("result", ["ok"])}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@_serialized
def disconnect_rtpmidi_peer(peer_id: int | str, *, timeout=3.0):
    """Disconnect a remote RTP MIDI peer by its router ID."""
    if peer_id is None:
        return {"success": False, "error": "Peer ID is required"}
    try:
        pid = int(peer_id)
    except (ValueError, TypeError):
        return {"success": False, "error": f"Invalid Peer ID: {peer_id}"}

    try:
        output = subprocess.check_output(
            ["rtpmidid-cli", "router.remove", str(pid)],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )
        parsed = parse_rtpmidid_cli_output(output)
        if "error" in parsed and parsed["error"]:
            return {"success": False, "error": str(parsed["error"])}
        return {"success": True, "result": parsed.get("result", ["ok"])}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


_MDNS_HOSTNAME_RE = re.compile(r"[^a-zA-Z0-9\-]")
_MDNS_MULTIDASH_RE = re.compile(r"-+")


def _derive_mdns_hostname(session_name: str) -> str:
    """Derive the mDNS hostname from an RTP session name.

    Mirrors the convention used by OSCMidi and other Apple MIDI clients:
    lowercased, non-alphanumeric replaced by hyphens, suffixed with -rtp.local.
    This is a best-effort heuristic; if the peer uses a different convention
    rtpmidid will simply create a waiting listener that connects once the peer
    actually appears on the network.
    """
    label = _MDNS_HOSTNAME_RE.sub("-", session_name).strip("-").lower()
    label = _MDNS_MULTIDASH_RE.sub("-", label)
    if not label:
        label = "rtpmidi"
    return f"{label}-rtp.local"


@_serialized
def reconcile_rtpmidi_autoconnect(usersettings):
    """Apply the saved target at startup and after peer/daemon disappearance.

    Called only by the port monitor or an explicit web request, never by MIDI
    callbacks. The deployment disables daemon-created discovery routes while
    retaining mDNS announcements, so there is one owner of outgoing sessions.
    """
    target = str(usersettings.get_setting_value("rtp_autoconnect") or "None").strip()
    info = get_rtpmidi_peers(timeout=1.5)
    if not info.get("success"):
        return info
    disabled = target.lower() in {"none", "disabled", ""}
    discovered = next((p for p in info["discovered_peers"]
                       if target in (p["name"], p["hostname"])), None)
    port = discovered["port"] if discovered else 5004

    candidate_hosts: set[str] = set()
    candidate_names: set[str] = {target}

    if discovered:
        host = discovered["hostname"]
        peer_name = discovered["name"]
        candidate_hosts.add(host)
        candidate_names.add(peer_name)
    elif "." not in target and ":" not in target:
        host = _derive_mdns_hostname(target)
        peer_name = target
        candidate_hosts.add(host)
        candidate_hosts.add(target)
    else:
        host = target
        peer_name = target
        candidate_hosts.add(host)

    for peer in info["connected_peers"]:
        if peer.get("kind") not in {"client", "listener"}:
            continue
        peer_host = peer.get("hostname", "")
        peer_name_val = peer.get("name", "")
        host_match = peer_host in candidate_hosts
        name_match = (
            peer_name_val in candidate_names
            or any(c and c.lower() in peer_name_val.lower() for c in candidate_names)
        )
        matches = peer.get("port") == port and (host_match or name_match)
        if disabled or not matches or peer.get("orphan"):
            result = disconnect_rtpmidi_peer(peer["id"], timeout=1.5)
            if not result.get("success"):
                return result
    if disabled:
        return {"success": True, "connected": False}
    # When the target is a service name not yet discovered via mDNS (typical
    # cold-boot race), derive the mDNS hostname and issue a connect.  rtpmidid
    # creates a waiting listener that auto-connects once the peer appears,
    # eliminating the multi-minute discovery delay.
    if discovered is None and "." not in target and ":" not in target:
        logger.info(
            "RTP autoconnect: peer '%s' not yet discovered via mDNS, "
            "trying derived hostname '%s:%d'",
            target, host, port,
        )
        return connect_rtpmidi_peer(host, port, target)
    return connect_rtpmidi_peer(host, port, peer_name)
