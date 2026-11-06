"""Causal bit-true frame sync: the frames the RTL will find must be the frames the float model finds."""

from __future__ import annotations

import numpy as np
import pytest

from model.coding import CODED_FRAME_SYMBOLS, build_cadus, encode_stream
from model.framesync_fixed import frame_sync_fixed
from model.receiver import RxConfig, frame_sync
from model.sync_fixed import ONE
from model.viterbi_fixed import quantize

ASM_SYMBOLS = 64


def _stream(frames: int, seed: int, sigma: float = 0.0) -> np.ndarray:
    """Serial soft stream at rail rms ONE (what the AGC delivers), plus noise of std sigma * ONE."""
    _, on_air = build_cadus(frames, seed)
    soft = (2 * encode_stream(on_air).astype(np.int64) - 1) * ONE
    rng = np.random.default_rng(seed)
    return soft + np.round(sigma * ONE * rng.standard_normal(soft.size)).astype(np.int64)


def _rotate(soft: np.ndarray, alternate: bool, swap: bool) -> np.ndarray:
    out = soft.copy()
    if swap:
        out[0::2], out[1::2] = soft[1::2], soft[0::2]
    if alternate:
        out[1::2] = -out[1::2]
    return out


@pytest.mark.parametrize(("alternate", "swap"), [(False, False), (True, False), (False, True), (True, True)])
def test_every_phase_hypothesis_matches_the_float_model(alternate: bool, swap: bool) -> None:
    # The RTL resolves the carrier's phase ambiguity from these flags; a wrong one decodes garbage. The first frame
    # must come out too: it is confirmed a frame later, from the delay line.
    soft = _rotate(_stream(6, 4, 0.5), alternate, swap)
    fixed = frame_sync_fixed(quantize(soft, 4, 10))
    cfg = RxConfig()
    assert fixed.frames == frame_sync(soft / np.mean(np.abs(soft)), cfg.sync_threshold, cfg.flywheel)
    assert [f[0] for f in fixed.frames] == [k * CODED_FRAME_SYMBOLS for k in range(6)]
    assert not any(fixed.flywheel)


def _blank_asms(soft: np.ndarray, frames: range, seed: int) -> np.ndarray:
    out = soft.copy()
    rng = np.random.default_rng(seed)
    for f in frames:
        s = f * CODED_FRAME_SYMBOLS
        out[s : s + ASM_SYMBOLS] = rng.choice([-ONE, ONE], ASM_SYMBOLS)
    return out


def test_flywheel_keeps_a_frame_with_a_missed_asm() -> None:
    # A noise burst on one ASM must not cost the frame: the frame is emitted, flagged, and RS decides.
    res = frame_sync_fixed(quantize(_blank_asms(_stream(6, 5), range(3, 4), 5), 4, 10))
    assert [f[0] for f in res.frames] == [k * CODED_FRAME_SYMBOLS for k in range(6)]
    assert res.flywheel == [False, False, False, True, False, False]


def test_lock_lost_after_flywheel_misses_then_reacquired() -> None:
    # Five missed ASMs in a row (flywheel 4): frames 3-6 come out flagged, frame 7 ends the lock, and the search
    # finds frame 8, confirmed at 9. Nothing is emitted twice.
    res = frame_sync_fixed(quantize(_blank_asms(_stream(12, 6), range(3, 8), 6), 4, 10), flywheel=4)
    assert [f[0] // CODED_FRAME_SYMBOLS for f in res.frames] == [0, 1, 2, 3, 4, 5, 6, 8, 9, 10, 11]
    assert res.flywheel == [False] * 3 + [True] * 4 + [False] * 4


def test_noise_only_produces_no_frames() -> None:
    # A false lock would feed garbage downstream. 600,000 symbols is about 4 s of a pass.
    rng = np.random.default_rng(1)
    u = quantize(np.round(ONE * rng.standard_normal(600_000)).astype(np.int64), 4, 10)
    assert frame_sync_fixed(u).frames == []


def test_carrier_slip_switches_hypothesis_without_losing_frames() -> None:
    # A 90 degree carrier slip moves the ASM to another hypothesis at the same position. Staying on the old one would
    # emit the flywheel's frames under the wrong phase (garbage) and lose them (data/results/framesync_fixed.csv).
    soft = _stream(12, 3)
    slip = 5 * CODED_FRAME_SYMBOLS
    soft[slip + 1 :: 2] *= -1
    res = frame_sync_fixed(quantize(soft, 4, 10))
    assert [(f[0] // CODED_FRAME_SYMBOLS, f[1]) for f in res.frames] == [(k, k >= 5) for k in range(12)]
    assert res.slips == 1
    assert not any(res.flywheel)


def test_timing_slip_followed_without_losing_frames() -> None:
    # The timing loop dropping one sample shifts every later ASM by a symbol, and on OQPSK also changes the phase
    # hypothesis. Seen on the bit-true chain at 2-3 dB (data/results/framesync_fixed.csv, seed 1).
    soft = _stream(12, 3)
    cut = 5 * CODED_FRAME_SYMBOLS + 5000
    soft = np.delete(soft, cut)
    res = frame_sync_fixed(quantize(soft, 4, 10))
    want = [k * CODED_FRAME_SYMBOLS - (k > 5) for k in range(12)]
    assert [f[0] for f in res.frames] == want
    assert res.slips == 1
    assert not any(res.flywheel)
