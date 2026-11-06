"""Causal bit-true frame sync: the frames the RTL will find must be the frames the float model finds."""

from __future__ import annotations

import numpy as np
import pytest

from model.coding import CADU_BITS, CODED_FRAME_SYMBOLS, build_cadus, encode_stream, nrzm_decode
from model.framesync_fixed import (
    POST_SYMBOLS,
    PRE_SYMBOLS,
    WINDOW_SYMBOLS,
    decode_windows,
    frame_sync_fixed,
    undo_levels,
    windows,
)
from model.receiver import RxConfig, _undo_hypothesis, frame_sync
from model.sync_fixed import ONE
from model.tests.framesync_stimulus import ambiguous_slip, blank_asms, rotate, stream, symbols
from model.viterbi_fixed import TRACEBACK_DEPTH, path_metric_bits, quantize, viterbi_fixed


@pytest.mark.parametrize(("alternate", "swap"), [(False, False), (True, False), (False, True), (True, True)])
def test_every_phase_hypothesis_matches_the_float_model(alternate: bool, swap: bool) -> None:
    # The RTL resolves the carrier's phase ambiguity from these flags; a wrong one decodes garbage. The first frame
    # must come out too: it is confirmed a frame later, from the delay line.
    soft = rotate(stream(6, 4, 0.5), alternate, swap)
    fixed = frame_sync_fixed(quantize(soft, 4, 10))
    cfg = RxConfig()
    assert fixed.frames == frame_sync(soft / np.mean(np.abs(soft)), cfg.sync_threshold, cfg.flywheel)
    assert [f[0] for f in fixed.frames] == [k * CODED_FRAME_SYMBOLS for k in range(6)]
    assert not any(fixed.flywheel)



def test_flywheel_keeps_a_frame_with_a_missed_asm() -> None:
    # A noise burst on one ASM must not cost the frame: the frame is emitted, flagged, and RS decides.
    res = frame_sync_fixed(quantize(blank_asms(stream(6, 5), range(3, 4), 5), 4, 10))
    assert [f[0] for f in res.frames] == [k * CODED_FRAME_SYMBOLS for k in range(6)]
    assert res.flywheel == [False, False, False, True, False, False]


def test_lock_lost_after_flywheel_misses_then_reacquired() -> None:
    # Five missed ASMs in a row (flywheel 4): frames 3-6 come out flagged, frame 7 ends the lock, and the search
    # finds frame 8, confirmed at 9. Nothing is emitted twice.
    res = frame_sync_fixed(quantize(blank_asms(stream(12, 6), range(3, 8), 6), 4, 10), flywheel=4)
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
    soft = stream(12, 3)
    slip = 5 * CODED_FRAME_SYMBOLS
    soft[slip + 1 :: 2] *= -1
    res = frame_sync_fixed(quantize(soft, 4, 10))
    assert [(f[0] // CODED_FRAME_SYMBOLS, f[1]) for f in res.frames] == [(k, k >= 5) for k in range(12)]
    assert res.slips == 1
    assert not any(res.flywheel)


def test_timing_slip_followed_without_losing_frames() -> None:
    # The timing loop dropping one sample shifts every later ASM by a symbol, and on OQPSK also changes the phase
    # hypothesis. Seen on the bit-true chain at 2-3 dB (data/results/framesync_fixed.csv, seed 1).
    soft = stream(12, 3)
    cut = 5 * CODED_FRAME_SYMBOLS + 5000
    soft = np.delete(soft, cut)
    res = frame_sync_fixed(quantize(soft, 4, 10))
    want = [k * CODED_FRAME_SYMBOLS - (k > 5) for k in range(12)]
    assert [f[0] for f in res.frames] == want
    assert res.slips == 1
    assert not any(res.flywheel)


@pytest.mark.parametrize(("alternate", "swap"), [(False, False), (True, False), (False, True), (True, True)])
def test_windows_decode_to_the_sent_frames(alternate: bool, swap: bool) -> None:
    # The window is everything the RTL Viterbi gets for a frame. Decoded the way the RTL decodes (sliding traceback
    # from state 0), the frame's bits must be the CADU sent, and the last one must leave the sliding traceback inside
    # the window: otherwise it would wait for the next frame, which never comes after a loss of lock.
    _, on_air = build_cadus(4, 7)
    soft = rotate((2 * encode_stream(on_air).astype(np.int64) - 1) * ONE, alternate, swap)
    u = quantize(np.concatenate([soft, np.zeros(PRE_SYMBOLS + POST_SYMBOLS, dtype=np.int64)]), 4, 10)
    res = frame_sync_fixed(u)
    wins, early = windows(u, res)
    assert early == 1  # the frame at symbol 0 has no run-in
    assert len(wins) == 3
    steps = WINDOW_SYMBOLS // 2
    first = PRE_SYMBOLS // 2
    assert first + CADU_BITS <= steps - TRACEBACK_DEPTH
    for k, w in enumerate(wins, start=1):
        assert (w.alternate, w.swap, w.flywheel) == (alternate, swap, False)
        sym = np.empty(WINDOW_SYMBOLS, dtype=np.int64)
        sym[0::2], sym[1::2] = w.pairs & 15, w.pairs >> 4
        bits, _ = viterbi_fixed(sym, 4, path_metric_bits(4), TRACEBACK_DEPTH, "zero")
        frame = np.packbits(nrzm_decode(bits[first : first + CADU_BITS], int(bits[first - 1])))
        assert np.array_equal(frame, on_air[k])


@pytest.mark.parametrize("scenario", ["noisy", "slip_back", "lock_lost"])
def test_continuous_viterbi_decodes_every_window(scenario: str) -> None:
    # The RTL Viterbi runs the windows back to back without a reset, so each window starts from the metrics the last
    # one left, which belong to another part of the stream: after an overlapping slip-back window, or after a loss of
    # lock, a gap of frames. The 64-step run-in must absorb that, or the frame's first bits (the ASM) go wrong.
    frames, seed, flywheel = {"noisy": (6, 3, 4), "slip_back": (6, 3, 4), "lock_lost": (12, 6, 3)}[scenario]
    _, on_air = build_cadus(frames, seed)
    soft = stream(frames, seed, 0.5)  # 6 dB Eb/N0
    cut = 2 * CODED_FRAME_SYMBOLS + 5000
    if scenario == "slip_back":
        soft = np.delete(soft, cut)
    if scenario == "lock_lost":
        soft = blank_asms(soft, range(3, 7), seed)
    u = symbols(soft)
    res = frame_sync_fixed(u, flywheel=flywheel)
    wins, early = windows(u, res)
    bits = decode_windows(wins)
    assert bits.shape == (len(wins), WINDOW_SYMBOLS // 2 - TRACEBACK_DEPTH)
    first = PRE_SYMBOLS // 2
    checked = 0
    for (start, _, _), w, b in zip(res.frames[early:], wins, bits, strict=False):
        k = round(start / CODED_FRAME_SYMBOLS)
        frame = np.packbits(nrzm_decode(b[first : first + CADU_BITS], int(b[first - 1])))
        if scenario == "slip_back" and k == 2:
            continue  # the cut is inside this frame
        skip = 4 if w.flywheel else 0  # a blanked ASM decodes to the noise sent in its place
        assert np.array_equal(frame[skip:], on_air[k][skip:]), f"frame {k}"
        checked += 1
    assert checked >= {"noisy": 5, "slip_back": 4, "lock_lost": 8}[scenario]
    if scenario == "lock_lost":
        assert 6 not in [round(f[0] / CODED_FRAME_SYMBOLS) for f in res.frames]  # a gap: the next window jumps


def test_decode_windows_of_nothing() -> None:
    assert decode_windows([]).shape == (0, WINDOW_SYMBOLS // 2 - TRACEBACK_DEPTH)


def test_undo_levels_negates_the_represented_level_exactly() -> None:
    # The RTL derotates by inverting bits. That must be the exact negation of the level the correlator and the
    # Viterbi use (v = 2u - 15), for every level, or one hypothesis would decode with a bias.
    u = np.tile(np.arange(16, dtype=np.int64), 2)
    for alternate in (False, True):
        for swap in (False, True):
            want = _undo_hypothesis((2 * u - 15).astype(float), alternate, swap)
            assert np.array_equal(2 * undo_levels(u, alternate, swap) - 15, want)


def test_slip_back_gives_overlapping_windows() -> None:
    # A timing slip of -1 symbol starts the next frame inside the previous window; a ring read by address emits both.
    soft = np.delete(stream(5, 3), 2 * CODED_FRAME_SYMBOLS + 5000)
    u = quantize(np.concatenate([soft, np.zeros(POST_SYMBOLS, dtype=np.int64)]), 4, 10)
    wins, early = windows(u, frame_sync_fixed(u))
    assert early == 1 and len(wins) == 4


def test_slip_tie_follows_the_earlier_peak() -> None:
    # The RTL searches 0, -1, +1, -2, +2 from its hit history; the model is the spec for that order. Peaks at e - 1
    # (hypothesis 1) and e + 1 (hypothesis 2), none at e: the earlier one is followed.
    e = 2 * CODED_FRAME_SYMBOLS + 12
    res = frame_sync_fixed(symbols(ambiguous_slip(stream(5, 3), e, 1, 2)))
    assert (e - 1 - 12, True, False) in res.frames
    assert res.slips == 2  # there, and back to hypothesis 0 at the next frame
