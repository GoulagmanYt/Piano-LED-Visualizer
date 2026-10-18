"""Measured GIL convoy mitigation for the Raspberry Pi Zero 2 W."""
import os
from pathlib import Path

from lib.log_setup import logger


def configure_midi_cpu_affinity(model_path=Path('/proc/device-tree/model')):
    """Pin this thread and its future workers before component startup.

    On the Zero 2 W, waking competing Python/ALSA threads on different cores
    amplifies GIL handoff delays. Other boards keep their existing affinity.
    PLV_MIDI_CPU_AFFINITY=off disables tuning; a CPU number overrides auto.
    """
    setting = os.environ.get('PLV_MIDI_CPU_AFFINITY', 'auto').strip().lower()
    if setting in {'off', 'none', 'disabled'}:
        return None
    get_affinity = getattr(os, 'sched_getaffinity', None)
    set_affinity = getattr(os, 'sched_setaffinity', None)
    if get_affinity is None or set_affinity is None:
        return None
    try:
        if setting == 'auto' and 'Raspberry Pi Zero 2 W' not in model_path.read_text():
            return None
        allowed = get_affinity(0)
        if not allowed:
            return None
        cpu = (2 if 2 in allowed else min(allowed)) if setting == 'auto' else int(setting)
        if cpu not in allowed:
            logger.warning('MIDI affinity CPU %s is outside the allowed CPU set', cpu)
            return None
        set_affinity(0, {cpu})
        logger.info('MIDI Python runtime affinity: CPU %s (PLV_MIDI_CPU_AFFINITY=%s)', cpu, setting)
        return cpu
    except (OSError, ValueError) as error:
        logger.debug('MIDI CPU affinity unchanged: %s', error)
        return None
