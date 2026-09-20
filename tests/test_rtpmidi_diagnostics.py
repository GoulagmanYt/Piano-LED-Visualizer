#!/usr/bin/env python3

import sys
import unittest

sys.path.append("./")
sys.path.append("../")

from unittest.mock import patch

from lib.rtpmidi_diagnostics import (
    connect_rtpmidi_peer,
    disconnect_rtpmidi_peer,
    get_rtpmidi_peers,
    parse_rtpmidid_cli_output,
    parse_rtpmidid_status,
)


DISCONNECTED_STATUS = {
    "result": {
        "mdns": {
            "remote_announcements": [
                {"hostname": "PC_Robin-2.local", "name": "OSCMidi", "port": 5004}
            ]
        },
        "router": [
            {
                "id": 7,
                "type": "network_rtpmidi_client_t",
                "peer": {
                    "status": "0",
                    "remote": {"hostname": "null", "name": "", "port": 0, "ssrc": 0},
                },
                "stats": {"recv": 5690, "sent": 0},
            },
            {
                "id": 5,
                "type": "local_alsa_listener_t",
                "name": "RtMidiOut Client-RtMidi output <-> OSCMidi",
                "status": "CONNECTED",
                "endpoints": [{"hostname": "PC_Robin-2.local", "port": "5004"}],
                "send_to": [7],
                "stats": {"recv": 0, "sent": 6095},
            },
        ],
    }
}


CONNECTED_STATUS = {
    "result": {
        "mdns": {
            "remote_announcements": [
                {"hostname": "PC_Robin-2.local", "name": "OSCMidi", "port": 5004}
            ]
        },
        "router": [
            {
                "id": 7,
                "type": "network_rtpmidi_client_t",
                "peer": {
                    "status": "CONNECTED",
                    "remote": {
                        "hostname": "PC_Robin-2.local",
                        "name": "OSCMidi",
                        "port": 5004,
                        "ssrc": 12345,
                    },
                },
                "stats": {"recv": 10, "sent": 20},
            },
            {
                "id": 5,
                "type": "local_alsa_listener_t",
                "name": "RtMidiOut Client-RtMidi output <-> OSCMidi",
                "status": "CONNECTED",
                "endpoints": [{"hostname": "PC_Robin-2.local", "port": "5004"}],
                "send_to": [7],
                "stats": {"recv": 2, "sent": 30},
            },
        ],
    }
}


class TestRtpMidiDiagnostics(unittest.TestCase):
    def test_cli_output_parser_ignores_echoed_request_line(self):
        output = """>>> {"method": "status", "params": []}
{
  "id": null,
  "result": {
    "router": []
  }
}
"""

        parsed = parse_rtpmidid_cli_output(output)

        self.assertIn("result", parsed)
        self.assertEqual(parsed["result"]["router"], [])

    def test_announced_osc_session_is_not_ready_until_network_peer_connects(self):
        diagnostics = parse_rtpmidid_status(
            DISCONNECTED_STATUS,
            play_port="rtpmidid:OSCMidi 129:2",
        )

        self.assertFalse(diagnostics["play_network_ready"])
        self.assertEqual(diagnostics["rtpmidi_peer_status"], "0")
        self.assertEqual(diagnostics["rtpmidi_remote_host"], "PC_Robin-2.local:5004")
        self.assertIn("alsa", diagnostics["rtpmidi_error_reason"].lower())
        self.assertIn("not connected", diagnostics["rtpmidi_error_reason"].lower())

    def test_connected_osc_session_is_ready_when_network_peer_has_remote_identity(self):
        diagnostics = parse_rtpmidid_status(
            CONNECTED_STATUS,
            play_port="rtpmidid:OSCMidi 129:2",
        )

        self.assertTrue(diagnostics["play_network_ready"])
        self.assertEqual(diagnostics["rtpmidi_peer_status"], "CONNECTED")
        self.assertEqual(diagnostics["rtpmidi_remote_host"], "PC_Robin-2.local:5004")
        self.assertIsNone(diagnostics["rtpmidi_error_reason"])

    def test_get_rtpmidi_peers_parses_discovered_and_connected(self):
        fake_output = """{
  "id": null,
  "result": {
    "mdns": {
      "remote_announcements": [
        {"hostname": "192.168.1.50", "name": "Studio_DAW", "port": 5004}
      ]
    },
    "router": [
      {
        "id": 12,
        "name": "Studio_DAW",
        "type": "network_rtpmidi_client_t",
        "peer": {
          "status": "CONNECTED",
          "remote": {"hostname": "192.168.1.50", "name": "Studio_DAW", "port": 5004},
          "latency_ms": {"average": 4.2}
        }
      }
    ]
  }
}"""
        with patch("subprocess.check_output", return_value=fake_output):
            peers = get_rtpmidi_peers()

        self.assertTrue(peers["success"])
        self.assertTrue(peers["daemon_running"])
        self.assertEqual(len(peers["discovered_peers"]), 1)
        self.assertEqual(peers["discovered_peers"][0]["name"], "Studio_DAW")
        self.assertEqual(len(peers["connected_peers"]), 1)
        self.assertEqual(peers["connected_peers"][0]["id"], 12)
        self.assertEqual(peers["connected_peers"][0]["latency_ms"], 4.2)

    def test_connect_rtpmidi_peer_invokes_cli(self):
        with patch("subprocess.check_output", return_value='{"id": null, "result": ["ok"]}') as mock_cmd:
            res = connect_rtpmidi_peer("192.168.1.50", 5004, "Studio_DAW")

        self.assertTrue(res["success"])
        mock_cmd.assert_called_once_with(
            ["rtpmidid-cli", "connect", "hostname=192.168.1.50", "port=5004", "name=Studio_DAW"],
            stderr=-2,
            text=True,
            timeout=3.0,
        )

    def test_disconnect_rtpmidi_peer_invokes_cli(self):
        with patch("subprocess.check_output", return_value='{"id": null, "result": ["ok"]}') as mock_cmd:
            res = disconnect_rtpmidi_peer(12)

        self.assertTrue(res["success"])
        mock_cmd.assert_called_once_with(
            ["rtpmidid-cli", "router.remove", "12"],
            stderr=-2,
            text=True,
            timeout=3.0,
        )

    def test_get_rtpmidi_peers_parses_waiting_endpoints_and_incoming_peers(self):
        fake_output = """{
  "id": null,
  "result": {
    "router": [
      {
        "id": 11,
        "name": "[WATING] <-> OSCMidi",
        "type": "local_alsa_listener_t",
        "status": "WAITING",
        "endpoints": [
          {"hostname": "192.168.1.92", "port": "5004"}
        ]
      },
      {
        "id": 2,
        "name": "PianoLedVisualizer",
        "type": "network_rtpmidi_multi_listener_t",
        "peers": [
          {
            "id": 88,
            "name": "RemotePad",
            "remote": {"hostname": "192.168.1.33", "port": 5004},
            "status": "CONNECTED",
            "latency_ms": {"average": 1.8}
          }
        ]
      }
    ]
  }
}"""
        with patch("subprocess.check_output", return_value=fake_output):
            peers = get_rtpmidi_peers()

        self.assertTrue(peers["success"])
        self.assertEqual(len(peers["connected_peers"]), 2)
        p1 = next(p for p in peers["connected_peers"] if p["id"] == 11)
        self.assertEqual(p1["name"], "OSCMidi")
        self.assertEqual(p1["hostname"], "192.168.1.92")
        self.assertEqual(p1["status"], "WAITING")
        p2 = next(p for p in peers["connected_peers"] if p["id"] == 88)
        self.assertEqual(p2["name"], "RemotePad")
        self.assertEqual(p2["latency_ms"], 1.8)


if __name__ == "__main__":
    unittest.main()
