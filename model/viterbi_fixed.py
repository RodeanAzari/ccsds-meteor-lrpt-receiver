"""Bit-true soft quantizer and Viterbi ACS (CLAUDE.md §3.6, §8.1 item 2).

Soft symbols arrive as s16 in the sync unit ONE (model/sync_fixed.py). The quantizer takes a power-of-two step, so
the RTL just selects bits. The decoder minimizes a distance metric on unsigned offset-binary symbols with modulo
path metrics (no normalization step). For the same quantized input it decides exactly as the float
coding.viterbi_decode() does, because per symbol the float correlation equals a constant minus this distance.

Traceback here is full-block from the best end state, as in the float model. The survivor scheme and traceback
depth are separate Phase D decisions.
"""

from __future__ import annotations

import numpy as np

from model.coding import _PRED, _SIGN_G1, _SIGN_G2, Bits
from model.ddc_fixed import Ints

K = 7  # constraint length, signal-spec.md
MEMORY = K - 1


def quantize(soft: Ints, bits: int, shift: int) -> Ints:
    """Midrise uniform quantizer, step 2^shift: u = clamp((soft >> shift) + 2^(bits-1), 0, 2^bits - 1).

    u represents (u - 2^(bits-1) + 1/2) steps, so the levels are symmetric about zero. Large u means bit 1.
    """
    top = (1 << bits) - 1
    out: Ints = np.clip((soft >> shift) + (1 << (bits - 1)), 0, top)
    return out


def max_branch_metric(soft_bits: int) -> int:
    return 2 * ((1 << soft_bits) - 1)


def path_metric_bits(soft_bits: int) -> int:
    """Smallest modulo width that compares correctly.

    Every state is reachable from the best state MEMORY steps earlier, so the path-metric spread is at most
    MEMORY * max_bm. ACS compares candidates (metric + branch metric), whose spread is at most (MEMORY + 1) * max_bm.
    Modulo comparison is correct while that spread is below 2^(bits-1).
    """
    return ((MEMORY + 1) * max_branch_metric(soft_bits)).bit_length() + 1


def viterbi_fixed(u: Ints, soft_bits: int, pm_bits: int) -> tuple[Bits, int]:
    """Decode a batch, shape (blocks, 2*n). Returns (bits, largest path-metric spread seen, in unwrapped units)."""
    if u.ndim == 1:
        bits, spread = viterbi_fixed(u[np.newaxis, :], soft_bits, pm_bits)
        return bits[0], spread
    top = (1 << soft_bits) - 1
    mask = (1 << pm_bits) - 1
    half = 1 << (pm_bits - 1)
    blocks, n_sym = u.shape
    n = n_sym // 2
    pm = np.zeros((blocks, 64), dtype=np.int64)  # modulo 2^pm_bits, as the registers hold them
    exact = np.zeros((blocks, 64), dtype=np.int64)  # unwrapped, only to report the spread
    decisions = np.zeros((n, blocks, 64), dtype=bool)
    p0, p1 = _PRED[:, 0], _PRED[:, 1]
    # Distance to an expected 1 is top - u, to an expected 0 is u.
    one10, one11 = _SIGN_G1[:, 0] > 0, _SIGN_G1[:, 1] > 0
    one20, one21 = _SIGN_G2[:, 0] > 0, _SIGN_G2[:, 1] > 0
    spread = 0
    for t in range(n):
        a = u[:, 2 * t, np.newaxis]
        b = u[:, 2 * t + 1, np.newaxis]
        bm0 = np.where(one10, top - a, a) + np.where(one20, top - b, b)
        bm1 = np.where(one11, top - a, a) + np.where(one21, top - b, b)
        m0 = (pm[:, p0] + bm0) & mask
        m1 = (pm[:, p1] + bm1) & mask
        choose1 = ((m1 - m0 + half) & mask) < half  # m1 - m0 < 0 modulo 2^pm_bits; ties keep branch 0
        decisions[t] = choose1
        pm = np.where(choose1, m1, m0)
        e0, e1 = exact[:, p0] + bm0, exact[:, p1] + bm1
        exact = np.where(choose1, e1, e0)
        exact -= exact.min(axis=1, keepdims=True)
        spread = max(spread, int(exact.max()))
    out = np.zeros((blocks, n), dtype=np.uint8)
    # Best end state: smallest metric, found with the same modulo comparison relative to state 0.
    state = np.argmin((pm - pm[:, :1] + half) & mask, axis=1)
    rows = np.arange(blocks)
    for t in range(n - 1, -1, -1):
        out[:, t] = state & 1
        state = (state >> 1) | (decisions[t, rows, state].astype(np.int64) << 5)
    return out, spread
