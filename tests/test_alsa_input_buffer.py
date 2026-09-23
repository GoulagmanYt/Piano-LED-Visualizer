import struct
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from lib import alsa_input_buffer


@pytest.mark.parametrize('accept', [True, False])
def test_input_pool_change_is_verified_and_does_not_change_output(monkeypatch, accept):
    size = 200
    def ioctl(fd, command, data, mutate):
        nonlocal size
        assert fd == 8
        if command & 255 == 1:
            struct.pack_into('=i', data, 0, 129)
        elif command & 255 == 0x4b:
            struct.pack_into('=iiiiii', data, 0, 129, 500, size, 250, 500, size)
        else:
            assert struct.unpack_from('=i', data, 4)[0] == 500
            if accept:
                size = struct.unpack_from('=i', data, 8)[0]
    monkeypatch.setattr(sys, 'platform', 'linux')
    monkeypatch.setitem(sys.modules, 'fcntl', SimpleNamespace(ioctl=ioctl))
    monkeypatch.setattr(alsa_input_buffer.os, 'listdir', lambda path: ['8', '9'])
    monkeypatch.setattr(alsa_input_buffer.os, 'readlink', lambda path: '/dev/snd/seq' if path.endswith('/8') else '/dev/null')
    if accept:
        assert alsa_input_buffer.enlarge_input_pools() == 1
        assert size == 2000
        assert alsa_input_buffer.enlarge_input_pools() == 0
    else:
        with pytest.raises(OSError, match='rejected'):
            alsa_input_buffer.enlarge_input_pools()


def test_non_linux_does_not_touch_descriptors(monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'win32')
    scan = Mock(side_effect=AssertionError('must not scan'))
    monkeypatch.setattr(alsa_input_buffer.os, 'listdir', scan)
    assert alsa_input_buffer.enlarge_input_pools() == 0
