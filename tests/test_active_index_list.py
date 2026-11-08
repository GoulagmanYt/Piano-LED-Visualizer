"""Regression tests for ActiveIndexList O(1) active-key tracking."""
import pytest
from lib.ledstrip import ActiveIndexList


def test_active_index_list_initializes_positive_indices():
    data = ActiveIndexList([0, 100, 0, -5, 250, 0])
    assert data.active_indices == {1, 4}
    assert list(data) == [0, 100, 0, -5, 250, 0]


def test_active_index_list_tracks_setitem_and_decay_to_zero():
    kl = ActiveIndexList(0 for _ in range(176))
    assert len(kl.active_indices) == 0

    # Light up three keys
    kl[21] = 1000
    kl[60] = 800
    kl[108] = 500
    assert kl.active_indices == {21, 60, 108}

    # In-place fade decay still positive
    kl[60] -= 300
    assert kl[60] == 500
    assert 60 in kl.active_indices

    # Decay to zero and below zero removes index from active_indices
    kl[60] = 0
    kl[108] = -10
    assert kl.active_indices == {21}

    # Clear last key
    kl[21] = 0
    assert len(kl.active_indices) == 0


def test_active_index_list_handles_negative_indices_and_slices():
    kl = ActiveIndexList([0, 0, 0, 0, 0])
    kl[-1] = 100
    assert kl.active_indices == {4}
    kl[-1] = 0
    assert kl.active_indices == set()

    # Slice assignment rebuilds active_indices accurately
    kl[1:4] = [50, 0, 75]
    assert kl.active_indices == {1, 3}


def test_active_index_list_clear_append_and_extend():
    kl = ActiveIndexList([10, 0, 20])
    assert kl.active_indices == {0, 2}

    kl.append(0)
    kl.append(30)
    assert kl.active_indices == {0, 2, 4}

    kl.extend([0, 40])
    assert kl.active_indices == {0, 2, 4, 6}

    kl.clear()
    assert kl == []
    assert kl.active_indices == set()
