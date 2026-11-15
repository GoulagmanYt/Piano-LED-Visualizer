"""Deterministic, lazy MIDI schedules shared by the source and its validator."""
import math
import random


def workload(profile='chords', *, chords=2000, interval=.020, rate=100,
             duration=30, seed=1):
    if (profile not in ('chords', 'poisson', 'isolated') or chords < 1
            or any(not math.isfinite(x) or x <= 0 for x in (interval, rate, duration))):
        raise ValueError('Invalid benchmark profile or workload parameters')
    if profile == 'chords':
        for chord in range(chords):
            offset = chord * interval
            yield offset, [0xB0, 64, 127]
            for note in range(48, 60):
                yield offset, [0x90, note, 80]
            for note in range(48, 60):
                yield offset, [0x80, note, 0]
            yield offset, [0xB0, 64, 0]
    elif profile == 'isolated':
        # More than a second of silence after each release/fade.
        offset = 1.0
        while offset + .1 < duration:
            yield offset, [0x90, 60, 90]
            yield offset + .1, [0x80, 60, 0]
            offset += 1.5
    else:
        rng = random.Random(seed)
        active = set()
        offset = 0.0
        while True:
            offset += rng.expovariate(rate)
            if offset >= duration:
                break
            if active and (len(active) == 10 or rng.random() < .5):
                note = rng.choice(sorted(active))
                active.remove(note)
                yield offset, [0x80, note, 0]
            else:
                note = rng.choice([n for n in range(48, 72) if n not in active])
                active.add(note)
                yield offset, [0x90, note, 80]
        for note in sorted(active):
            yield duration, [0x80, note, 0]


def transmit(schedule, output, epoch, *, clock, sleep):
    """Never move a deadline when late; include lateness in the source report."""
    import hashlib

    digest = hashlib.sha256()
    sent = 0
    lateness_total = lateness_max = 0.0
    first = last = None
    for offset, data in schedule:
        deadline = epoch + offset
        while (remaining := deadline - clock()) > 0:
            sleep(remaining)
        now = clock()
        lateness = max(0.0, now - deadline)
        lateness_total += lateness
        lateness_max = max(lateness_max, lateness)
        output(data)
        encoded = bytes(data)
        digest.update(len(encoded).to_bytes(4, 'big') + encoded)
        sent += 1
        first = now if first is None else first
        last = now
    return {'sent': sent, 'hash': digest.hexdigest(), 'epoch': epoch,
                'first_send': first, 'last_send': last,
                'send_span_s': 0 if first is None else last - first,
                'scheduling_lateness_avg_ms': 1000 * lateness_total / max(1, sent),
                'scheduling_lateness_max_ms': 1000 * lateness_max}
