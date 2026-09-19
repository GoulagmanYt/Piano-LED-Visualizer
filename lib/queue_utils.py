def drain_deque(queue, limit=None):
    drained = []
    while limit is None or len(drained) < limit:
        try:
            drained.append(queue.popleft())
        except IndexError:
            break
    return drained
