"""Quantized soft symbols of a convolutionally coded random bit stream: what the Viterbi blocks see.

Antipodal symbols at the sync unit ONE (the AGC's rail rms) plus AWGN, quantized as the receiver does
(viterbi_fixed.quantize(), 4 bits, step ONE/4: ADR 0005).
"""

from __future__ import annotations

import numpy as np

from model.coding import conv_encode
from model.sync_fixed import ONE
from model.viterbi_fixed import quantize

SOFT_BITS = 4
SHIFT = 10  # step ONE/4 = 2^10 (ADR 0005)


def coded_symbols(n_bits: int, ebn0_db: float, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Return (sent bits, quantized symbols G1, G2, G1, ...) for n_bits random bits at ebn0_db, code rate 1/2."""
    rng = np.random.default_rng(seed)
    bits = rng.integers(0, 2, n_bits, dtype=np.uint8)
    coded = conv_encode(bits).astype(np.int64)
    sigma = ONE / np.sqrt(2 * 0.5 * 10 ** (ebn0_db / 10))
    soft = (2 * coded - 1) * ONE + np.round(sigma * rng.standard_normal(coded.size)).astype(np.int64)
    return bits, quantize(soft, SOFT_BITS, SHIFT)


def pairs(u: np.ndarray) -> list[int]:
    """Pack each step's (G1, G2) symbols as s_tdata = {b, a}."""
    return [int(a) | (int(b) << SOFT_BITS) for a, b in zip(u[0::2], u[1::2], strict=True)]
