"""Merge MIDI tracks while keeping musical hand roles separate from wire channels."""

import mido


def merge_learning_tracks(mid):
    """Return merged messages and parallel roles: 1 right, 2 left, 0 accompaniment.

    Conductor/empty tracks don't consume a hand. For a multitrack score, the
    first two note-bearing tracks are the hands. For a single playable track,
    the first two note channels are the hands. Remaining parts accompany them.
    Original MIDI channels and the source MidiFile are never modified.
    """
    if mid.type == 2:
        raise ValueError("Asynchronous MIDI type 2 tracks cannot form one learning timeline")
    playable = [i for i, track in enumerate(mid.tracks)
                if any(msg.type == "note_on" and msg.velocity > 0 for msg in track)]
    track_hands = {index: rank + 1 for rank, index in enumerate(playable[:2])}
    channel_hands = {}
    if len(playable) == 1:
        channels = sorted({msg.channel for msg in mid.tracks[playable[0]]
                           if msg.type == "note_on" and msg.velocity > 0})
        channel_hands = {channel: rank + 1 for rank, channel in enumerate(channels[:2])}

    events = []
    duration = 0
    for index, track in enumerate(mid.tracks):
        tick = 0
        for msg in track:
            tick += msg.time
            duration = max(duration, tick)
            if msg.type == "end_of_track":
                continue
            hand = track_hands.get(index, 0)
            if len(playable) == 1 and index == playable[0]:
                hand = channel_hands.get(getattr(msg, "channel", None), 0)
            events.append((tick, msg, hand if not msg.is_meta else 0))
    events.sort(key=lambda event: event[0])  # stable: track order at equal ticks
    messages, hands = [], []
    previous = 0
    for tick, msg, hand in events:
        messages.append(msg.copy(time=tick - previous))
        hands.append(hand)
        previous = tick
    messages.append(mido.MetaMessage("end_of_track", time=duration - previous))
    hands.append(0)
    return mido.MidiTrack(messages), hands
