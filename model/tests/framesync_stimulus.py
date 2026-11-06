"""Frame-sync stimulus shared by the model tests and the RTL tests (tb/cocotb/framesync_tb.py), so both judge the
same streams."""

from __future__ import annotations

import numpy as np

from model.coding import CODED_FRAME_SYMBOLS, build_cadus, encode_stream
from model.ddc_fixed import Ints
from model.framesync_fixed import POST_SYMBOLS, PRE_SYMBOLS, patterns
from model.sync_fixed import ONE
from model.viterbi_fixed import quantize

ASM_SYMBOLS = 64


def stream(frames: int, seed: int, sigma: float = 0.0) -> Ints:
    """Serial soft stream at rail rms ONE (what the AGC delivers), plus noise of std sigma * ONE."""
    _, on_air = build_cadus(frames, seed)
    soft = (2 * encode_stream(on_air).astype(np.int64) - 1) * ONE
    rng = np.random.default_rng(seed)
    out: Ints = soft + np.round(sigma * ONE * rng.standard_normal(soft.size)).astype(np.int64)
    return out


def rotate(soft: Ints, alternate: bool, swap: bool) -> Ints:
    out = soft.copy()
    if swap:
        out[0::2], out[1::2] = soft[1::2], soft[0::2]
    if alternate:
        out[1::2] = -out[1::2]
    return out


def blank_asms(soft: Ints, frames: range, seed: int) -> Ints:
    out = soft.copy()
    rng = np.random.default_rng(seed)
    for f in frames:
        s = f * CODED_FRAME_SYMBOLS
        out[s : s + ASM_SYMBOLS] = rng.choice([-ONE, ONE], ASM_SYMBOLS)
    return out


def ambiguous_slip(soft: Ints, e: int, a: int, b: int) -> Ints:
    """Replace the ASM expected at e with hypothesis a's pattern at e - 1 blended with b's at e + 1: full-scale
    symbols where the two agree, the smallest level where they don't. Both pass the threshold and nothing hits at e,
    so only the slip search order (-1 before +1) decides which one is followed."""
    pats = patterns()
    n = pats.shape[1]
    acc = np.zeros(n + 2, dtype=np.int64)
    acc[:n] += pats[a]
    acc[2:] += pats[b]
    full = 15 * 512  # +-7.5 steps of ONE/4: u = 15 or 0
    out = soft.copy()
    out[e - 1 : e + 1 + n] = np.where(acc > 0, full, np.where(acc < 0, -full, 512))
    return out


def symbols(soft: Ints) -> Ints:
    """Quantize, with a zero tail long enough for the last frame's window to complete."""
    return quantize(np.concatenate([soft, np.zeros(PRE_SYMBOLS + POST_SYMBOLS, dtype=np.int64)]), 4, 10)
