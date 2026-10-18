from unittest.mock import Mock

import pytest

from lib.midi_runtime_tuning import configure_midi_cpu_affinity


@pytest.mark.parametrize('model,setting,allowed,expected', [
    ('Raspberry Pi Zero 2 W Rev 1.0\0', 'auto', {0, 1, 2, 3}, 2),
    ('Raspberry Pi Zero 2 W Rev 1.0', 'auto', {1, 3}, 1),
    ('Raspberry Pi 5 Model B Rev 1.0', 'auto', {0, 1, 2, 3}, None),
    ('Raspberry Pi Zero 2 W Rev 1.0', 'off', {0, 1, 2, 3}, None),
    ('Raspberry Pi Zero 2 W Rev 1.0', '3', {0, 1, 2, 3}, 3),
    ('Raspberry Pi Zero 2 W Rev 1.0', '9', {0, 1, 2, 3}, None),
    ('Raspberry Pi Zero 2 W Rev 1.0', 'broken', {0, 1, 2, 3}, None),
])
def test_affinity_policy_is_limited_and_respects_service_cpu_restrictions(
        monkeypatch, tmp_path, model, setting, allowed, expected):
    model_path = tmp_path / 'model'
    model_path.write_text(model)
    monkeypatch.setenv('PLV_MIDI_CPU_AFFINITY', setting)
    monkeypatch.setattr('lib.midi_runtime_tuning.os.sched_getaffinity',
                        lambda pid: allowed, raising=False)
    setter = Mock()
    monkeypatch.setattr('lib.midi_runtime_tuning.os.sched_setaffinity', setter, raising=False)
    assert configure_midi_cpu_affinity(model_path) == expected
    if expected is None:
        setter.assert_not_called()
    else:
        setter.assert_called_once_with(0, {expected})


def test_unsupported_os_or_denied_affinity_leaves_runtime_running(monkeypatch, tmp_path):
    model_path = tmp_path / 'model'
    model_path.write_text('Raspberry Pi Zero 2 W Rev 1.0')
    monkeypatch.setenv('PLV_MIDI_CPU_AFFINITY', 'auto')
    monkeypatch.setattr('lib.midi_runtime_tuning.os.sched_getaffinity',
                        lambda pid: {0, 1, 2, 3}, raising=False)
    monkeypatch.setattr('lib.midi_runtime_tuning.os.sched_setaffinity',
                        Mock(side_effect=OSError('denied')), raising=False)
    assert configure_midi_cpu_affinity(model_path) is None
    assert configure_midi_cpu_affinity(tmp_path / 'missing') is None
