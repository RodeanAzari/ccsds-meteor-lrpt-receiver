"""Bit-true RRC matched filter: s16 DDC output -> 57-tap FIR -> s16 (CLAUDE.md §8.1 item 2).

Causal, at the widths and rounding the RTL in rtl/sync/ will use. Formats are in docs/fixed-point.md. Same
conventions as model/ddc_fixed.py: round-half-up, explicit saturation on every narrowing.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from model.channel import Complex
from model.ddc_fixed import OUT_BITS as DDC_BITS
from model.ddc_fixed import Ints, ddc_fixed_rails, round_shift, saturate
from model.receiver import RxConfig, rrc_taps

RRC_FRAC = 17  # taps s1.17, the DSP48E1 18-bit B port; max tap 0.32, DC gain 1.00
OUT_BITS = 16  # |in| <= 22,900 (comp FIR bound, fixed-point.md) * sum|h| 1.374 = 31,465 < 32,767: cannot saturate


def taps(cfg: RxConfig) -> Ints:
    """Quantized RRC taps. Rounding keeps them symmetric, so the RTL can fold them through the DSP pre-adder."""
    q: Ints = np.round(rrc_taps(cfg.fs / cfg.decimation, cfg.rrc_span) * (1 << RRC_FRAC)).astype(np.int64)
    return q


def rrc_fixed(i: Ints, q: Ints, cfg: RxConfig) -> tuple[Ints, Ints]:
    """Filter each rail with the quantized taps; accumulator exact (<= 40 bits), output s16 rounded and saturated."""
    h = taps(cfg)
    out = [saturate(round_shift(np.convolve(x, h)[: x.size], RRC_FRAC), OUT_BITS) for x in (i, q)]
    return out[0], out[1]


def ddc_rrc_fixed(raw: npt.NDArray[np.uint8], cfg: RxConfig) -> Complex:
    """Bit-true DDC then RRC; output scaled by 2^-15 so it can feed receiver.demodulate_filtered()."""
    i, q = rrc_fixed(*ddc_fixed_rails(raw, cfg), cfg)
    out: Complex = ((i + 1j * q) / (1 << (DDC_BITS - 1))).astype(np.complex128)
    return out
