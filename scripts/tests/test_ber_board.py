"""count_errors and upper95: the arithmetic every hardware BER point rests on.

Why it matters: a CADU matched to the wrong sent frame counts ~50% bit errors; one that is skipped or counted twice
shifts every later match; a missing frame must not shift the count. The upper bound is what a point with fewer than
100 errors reports (CLAUDE.md), so it must be the standard Poisson bound (3/n at zero errors).
"""

from __future__ import annotations

import numpy as np
import pytest

from scripts.ber_board import POST, PRE, UNMATCHED, count_errors, upper95


def frames(n: int, seed: int = 1) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 256, (n, 1024), dtype=np.uint8)


def flip(frame: np.ndarray, bits: list[int]) -> bytes:
    b = np.unpackbits(frame.copy())
    for k in bits:
        b[k] ^= 1
    return bytes(np.packbits(b))


def test_known_errors_counted_in_region_only() -> None:
    t = frames(10)
    # frame 1: 3 errors in the data bytes; 2 in the ASM (outside both regions); frame 2: 1 error in RS parity
    rx = [flip(t[1], [100, 2000, 7000, 3, 9]), flip(t[2], [8 * 900 + 1]), bytes(t[3])]
    pre = count_errors(rx, t, PRE)
    post = count_errors(rx, t, POST)
    assert (pre.matched, pre.unmatched, pre.errors, pre.bits) == (3, 0, 4, 3 * 8160)
    assert (post.matched, post.errors, post.bits) == (3, 3, 3 * 7136)


def test_missing_frames_do_not_shift_matches() -> None:
    t = frames(20)
    rx = [bytes(t[k]) for k in (1, 2, 5, 6, 19)]  # 3, 4 and 7..18 never came
    c = count_errors(rx, t, PRE)
    assert (c.matched, c.unmatched, c.errors) == (5, 0, 0)


def test_garbage_is_unmatched_not_errors() -> None:
    t = frames(10)
    junk = bytes(frames(1, seed=99)[0])  # no sent frame: ~50% bit errors against all of them
    c = count_errors([bytes(t[1]), junk, bytes(t[2])], t, PRE)
    assert (c.matched, c.unmatched, c.errors) == (2, 1, 0)


def test_threshold_boundary() -> None:
    t = frames(5)
    n = 8160
    at = int(UNMATCHED * n)  # exactly at the threshold still matches; one more bit does not
    assert count_errors([flip(t[1], list(range(32, 32 + at)))], t, PRE).matched == 1
    assert count_errors([flip(t[1], list(range(32, 32 + at + 1)))], t, PRE).unmatched == 1


def test_no_frame_matched_twice() -> None:
    t = frames(5)
    c = count_errors([bytes(t[2]), bytes(t[2])], t, PRE)  # a repeat: only frames after the last match qualify
    assert (c.matched, c.unmatched, c.errors) == (1, 1, 0)
    t = frames(12)
    c = count_errors([bytes(t[1]), bytes(t[5]), bytes(t[5])], t, PRE)  # the same after a jump over missing frames
    assert (c.matched, c.unmatched, c.errors) == (2, 1, 0)


def test_upper_bound() -> None:
    assert upper95(0, 1_000_000) == pytest.approx(2.9957e-6, rel=1e-3)  # -ln(0.05) / n
    assert upper95(10, 1_000_000) == pytest.approx(17.0e-6, rel=0.01)  # chi2(0.95, 22) / 2 / n
    assert upper95(5, 10) > 0.5
