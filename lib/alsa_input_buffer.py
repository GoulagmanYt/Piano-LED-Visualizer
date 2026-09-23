"""Size the kernel ALSA input FIFO via its public Linux UAPI.

RtMidi exposes no pool-size setter. Only sequencer descriptors belonging to
this process are inspected; no C++ private pointers or foreign clients are used.
"""
import os
import struct
import sys


def enlarge_input_pools(events=2000):
    if not sys.platform.startswith('linux'):
        return 0
    import fcntl
    changed = 0
    # Linux asm-generic ioctl encoding (Raspberry Pi ARM/ARM64 and x86).
    client_id_ioctl = (2 << 30) | (4 << 16) | (ord('S') << 8) | 0x01
    get_pool_ioctl = (3 << 30) | (88 << 16) | (ord('S') << 8) | 0x4b
    set_pool_ioctl = (1 << 30) | (88 << 16) | (ord('S') << 8) | 0x4c
    for name in os.listdir('/proc/self/fd'):
        try:
            if os.readlink('/proc/self/fd/' + name) != '/dev/snd/seq':
                continue
            fd = int(name)
            client = bytearray(4)
            fcntl.ioctl(fd, client_id_ioctl, client, True)
            pool = bytearray(88)
            pool[:4] = client
            fcntl.ioctl(fd, get_pool_ioctl, pool, True)
            size = struct.unpack_from('=i', pool, 8)[0]
            if 0 < size < events:
                struct.pack_into('=i', pool, 8, events)
                fcntl.ioctl(fd, set_pool_ioctl, pool, True)
                fcntl.ioctl(fd, get_pool_ioctl, pool, True)
                if struct.unpack_from('=i', pool, 8)[0] < events:
                    raise OSError('ALSA kernel rejected input pool size')
                changed += 1
        except FileNotFoundError:
            # A descriptor can close between enumeration and readlink.
            continue
    return changed
