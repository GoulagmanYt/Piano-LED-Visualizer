from unittest.mock import Mock, patch

import mido

from lib.midi_queues import MidiQueues
from lib.rtpmidi_diagnostics import connect_rtpmidi_peer, reconcile_rtpmidi_autoconnect


def test_disabled_output_keeps_visualization_without_retaining_forwarded_notes():
    queues = MidiQueues()
    queues.set_forwarding_enabled(False)
    note = mido.Message('note_on', note=60)
    for _ in range(1000):
        queues.enqueue_all_live(note, is_note=True)
    assert len(queues.live_visualizer_queue) == 1000
    assert not queues.live_forward_queue
    assert not queues.enqueue_live_forward(note)
    assert not queues.enqueue_scheduled_forward(note)
    queues.set_forwarding_enabled(True)
    assert not queues.live_forward_queue
    queues.enqueue_all_live(note)
    assert len(queues.live_forward_queue) == 1
    queues.set_forwarding_enabled(False)
    assert not queues.live_forward_queue


def test_rtp_connect_preserves_custom_reliable_tcp_port():
    from webinterface import webinterface, app_state
    from webinterface.views_api import api_rtpmidi_connect
    settings = Mock()
    with webinterface.test_request_context('/api/rtpmidi_connect', method='POST',
                                          json={'hostname': 'piano.local', 'port': 5004}), \
         patch.object(app_state, 'usersettings', settings), \
         patch.object(app_state, 'midiports', None), \
         patch('webinterface.views_api.connect_rtpmidi_peer', return_value={'success': True}):
        response, status = api_rtpmidi_connect()
        assert status == 200
    assert all(call.args[0] != 'reliable_midi_port' for call in settings.change_setting_value.call_args_list)


def test_autoconnect_retries_when_peer_appears_after_startup():
    settings = Mock()
    settings.get_setting_value.return_value = 'Studio'
    info = {'success': True, 'connected_peers': [], 'discovered_peers': []}
    with patch('lib.rtpmidi_diagnostics.get_rtpmidi_peers', return_value=info), \
         patch('lib.rtpmidi_diagnostics.connect_rtpmidi_peer', return_value={'success': True}) as connect:
        assert reconcile_rtpmidi_autoconnect(settings)['waiting']
        connect.assert_not_called()
        info['discovered_peers'].append({'name': 'Studio', 'hostname': 'pc.local', 'port': 5006})
        reconcile_rtpmidi_autoconnect(settings)
        connect.assert_called_once_with('pc.local', 5006, 'Studio')


def test_disabled_autoconnect_removes_outgoing_routes_only():
    settings = Mock()
    settings.get_setting_value.return_value = 'None'
    info = {'success': True, 'discovered_peers': [], 'connected_peers': [
        {'id': 3, 'kind': 'listener'}, {'id': 4, 'kind': 'client'}, {'id': 5}]}
    with patch('lib.rtpmidi_diagnostics.get_rtpmidi_peers', return_value=info), \
         patch('lib.rtpmidi_diagnostics.disconnect_rtpmidi_peer', return_value={'success': True}) as remove:
        assert reconcile_rtpmidi_autoconnect(settings)['success']
        assert [c.args[0] for c in remove.call_args_list] == [3, 4]


def test_connect_does_not_confuse_different_ports_on_same_host():
    info = {'connected_peers': [{'id': 1, 'hostname': 'pc.local', 'name': 'Studio', 'port': 5006, 'status': '3'}]}
    with patch('lib.rtpmidi_diagnostics.get_rtpmidi_peers', return_value=info), \
         patch('subprocess.check_output', return_value='{"result": ["ok"]}') as command:
        assert connect_rtpmidi_peer('pc.local', 5004, 'Studio')['success']
        assert command.call_count == 1


def test_waiting_listener_is_not_recreated_on_each_poll():
    info = {'connected_peers': [{'id': 1, 'hostname': 'pc.local', 'name': 'Studio', 'port': 5004, 'kind': 'listener', 'status': 'WAITING'}]}
    with patch('lib.rtpmidi_diagnostics.get_rtpmidi_peers', return_value=info), \
         patch('subprocess.check_output') as command:
        assert connect_rtpmidi_peer('pc.local', 5004, 'Studio')['success']
        command.assert_not_called()


def test_orphan_client_removed_without_removing_active_session():
    base = {'hostname': 'pc.local', 'name': 'Studio', 'port': 5004, 'kind': 'client', 'status': '3'}
    info = {'connected_peers': [dict(base, id=1, orphan=True), dict(base, id=2, orphan=False)]}
    with patch('lib.rtpmidi_diagnostics.get_rtpmidi_peers', return_value=info), \
         patch('lib.rtpmidi_diagnostics.disconnect_rtpmidi_peer', return_value={'success': True}) as remove:
        assert connect_rtpmidi_peer('pc.local', 5004, 'Studio')['success']
        remove.assert_called_once_with(1, timeout=1.5)


def test_midi_recording_filename_has_no_colons_and_is_valid():
    from lib.song_file_security import validate_song_filename
    from lib.savemidi import SaveMIDI
    import datetime

    # Test format generated in views_api
    now = datetime.datetime.now()
    recorded_name = now.strftime("%Y-%m-%d_%H-%M-%S")
    assert ":" not in recorded_name
    valid_name = validate_song_filename(f"{recorded_name}_main.mid")
    assert valid_name == f"{recorded_name}_main.mid"

    # Test SaveMIDI sanitizes input if colons are somehow passed
    saving = SaveMIDI()
    saving.messages_to_save = {"main": []}
    menu = Mock()
    saving.add_instance(menu)
    with patch('mido.MidiFile.save') as mock_save:
        saving.save("2026-09-23 18:56")
        mock_save.assert_called_once_with("Songs/2026-09-23 18-56_main.mid")
    menu.render_message.assert_called_once_with("File saved", "2026-09-23 18-56.mid", 1500)


def test_legacy_colon_song_migration():
    from webinterface.views_api import _migrate_legacy_colon_song_files
    from pathlib import Path

    mock_entry = Mock()
    mock_entry.name = "2026-09-23 18:56_main.mid"
    with patch.object(Path, 'is_dir', return_value=True), \
         patch.object(Path, 'iterdir', return_value=[mock_entry]), \
         patch.object(Path, 'exists', return_value=False):
        _migrate_legacy_colon_song_files(base_dir="FakeSongs")
        mock_entry.rename.assert_called_once()
        target_path = mock_entry.rename.call_args[0][0]
        assert "2026-09-23 18-56_main.mid" in str(target_path)


def test_usersettings_auto_heals_reliable_midi_port_5004(tmp_path):
    from lib.usersettings import UserSettings
    import xml.etree.ElementTree as ET

    config_path = tmp_path / "settings.xml"
    default_config_path = tmp_path / "default_settings.xml"

    default_config_path.write_text("<settings><reliable_midi_port>5056</reliable_midi_port></settings>")
    config_path.write_text("<settings><reliable_midi_port>5004</reliable_midi_port></settings>")

    settings = UserSettings(config=str(config_path), default_config=str(default_config_path))
    assert settings.get_setting_value("reliable_midi_port") == "5056"


def test_stop_animations_leaves_flag_false():
    from lib.functions import stop_animations

    class FakeMenu:
        is_idle_animation_running = True
        is_animation_running = True
        t = None

    menu = FakeMenu()
    stop_animations(menu)
    assert menu.is_animation_running is False
    assert menu.is_idle_animation_running is False


def test_profile_manager_closes_connections(tmp_path):
    import sqlite3
    from lib.profile_manager import ProfileManager

    db_path = str(tmp_path / "test_profiles.db")
    pm = ProfileManager(db_path=db_path, songs_dir=str(tmp_path))

    with pm._connect() as conn:
        conn.execute("SELECT 1")
        saved_conn = conn

    # Attempting to execute on saved_conn outside the with block must fail because it's closed
    try:
        saved_conn.execute("SELECT 1")
        assert False, "Connection should have been closed"
    except sqlite3.ProgrammingError:
        pass  # Expected: Cannot operate on a closed database

