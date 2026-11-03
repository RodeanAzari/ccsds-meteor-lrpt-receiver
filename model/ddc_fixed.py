"""Bit-true DDC: ingest -> DC block -> NCO + mixer -> CIC /4 -> compensation FIR (CLAUDE.md §8.1 item 2).

Streaming and causal, at the widths and rounding the RTL in rtl/ddc/ will use. Every format is in
docs/fixed-point.md; the NCO and CIC choices are ADRs 0003 and 0004. Rounding is round-half-up
(add half, arithmetic shift right) everywhere, and every narrowing saturates explicitly.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from model.channel import Complex
from model.receiver import RxConfig, comp_fir_taps

Ints = npt.NDArray[np.int64]

INGEST_BITS = 9  # 2*raw - 255: odd integers in [-255, 255], midpoint 127.5 exact (signal-spec.md, cu8)
DC_BITS = 10  # DC block output; a step in DC can double the input swing (fixed-point.md)
DC_FRAC = 12  # extra fraction bits in the DC block accumulator; dead band 2^(DC_K-1-DC_FRAC) = 1/8 LSB
DC_K = 10  # pole 1 - 2^-10: corner fs * 2^-10 / 2pi = 159 Hz at 1.024 MS/s
PHASE_BITS = 32  # NCO accumulator; resolution 1.024e6 / 2^32 = 0.24 mHz (ADR 0003)
LUT_PHASE_BITS = 12  # phase bits into the sine table: 2 quadrant + 10 address (ADR 0003)
NCO_BITS = 16  # sine/cosine amplitude, peak 2^15 - 1 (ADR 0003)
MIX_SHIFT = 11  # |mixer out| <= 511*sqrt2*32767 / 2^11 = 11563 < 2^15 / 1.98 (FIR sum|h|): FIR cannot saturate
MIX_BITS = 16
CIC_ORDER = 3  # ADR 0004; also RxConfig.cic_order
CIC_R = 4  # ADR 0004; also RxConfig.decimation
CIC_REG_BITS = MIX_BITS + CIC_ORDER * 2  # Hogenauer growth N*log2(R*M), M = 1: 16 + 6 = 22
CIC_SHIFT = CIC_ORDER * 2  # CIC gain (R*M)^N = 64 = 2^6, removed exactly
COMP_FRAC = 17  # tap format s1.17, an 18-bit DSP48E1 B port; max |tap| is 0.79
OUT_BITS = 16


def round_shift(x: Ints, s: int) -> Ints:
    out: Ints = (x + (1 << (s - 1))) >> s
    return out


def saturate(x: Ints, bits: int) -> Ints:
    out: Ints = np.clip(x, -(1 << (bits - 1)), (1 << (bits - 1)) - 1)
    return out


def wrap(x: Ints, bits: int) -> Ints:
    """Two's-complement wraparound to `bits`, what a register of that width does. Legal only inside the CIC."""
    half = 1 << (bits - 1)
    out: Ints = ((x + half) & ((1 << bits) - 1)) - half
    return out


def ingest(raw: npt.NDArray[np.uint8]) -> tuple[Ints, Ints]:
    """Interleaved cu8 -> signed I and Q, value 2*raw - 255 (exactly 255 * the float model's ingest)."""
    v = 2 * raw.astype(np.int64) - 255
    return v[0::2], v[1::2]


def dc_block(x: Ints) -> Ints:
    """y[n] = x[n] - x[n-1] + (1 - 2^-DC_K) y[n-1], accumulator with DC_FRAC fraction bits."""
    acc, prev = 0, 0
    half_k, half_f = 1 << (DC_K - 1), 1 << (DC_FRAC - 1)
    lo, hi = -(1 << (DC_BITS - 1)), (1 << (DC_BITS - 1)) - 1
    out = [0] * x.size
    for n, v in enumerate(x.tolist()):
        acc += ((v - prev) << DC_FRAC) - ((acc + half_k) >> DC_K)
        prev = v
        out[n] = min(max((acc + half_f) >> DC_FRAC, lo), hi)
    return np.array(out, dtype=np.int64)


def nco_lut() -> Ints:
    """Quarter-wave table, sampled half a step off zero so the four quadrants mirror without a special case."""
    size = 1 << (LUT_PHASE_BITS - 2)
    theta = 2 * np.pi * (np.arange(size) + 0.5) / (1 << LUT_PHASE_BITS)
    lut: Ints = np.round(((1 << (NCO_BITS - 1)) - 1) * np.sin(theta)).astype(np.int64)
    return lut


def freq_word(offset_hz: float, fs: float) -> int:
    return round(offset_hz / fs * (1 << PHASE_BITS)) % (1 << PHASE_BITS)


def nco(n: int, word: int) -> tuple[Ints, Ints]:
    """(cos, sin) for samples 0..n-1, phase[k] = k * word mod 2^PHASE_BITS."""
    lut = nco_lut()
    phase = (np.arange(n, dtype=np.int64) * word) & ((1 << PHASE_BITS) - 1)
    p = phase >> (PHASE_BITS - LUT_PHASE_BITS)
    quadrant = p >> (LUT_PHASE_BITS - 2)
    addr = p & (lut.size - 1)
    a, b = lut[addr], lut[lut.size - 1 - addr]
    sin = np.select([quadrant == 0, quadrant == 1, quadrant == 2], [a, b, -a], -b)
    cos = np.select([quadrant == 0, quadrant == 1, quadrant == 2], [b, -a, -b], a)
    return cos, sin


def mix(i: Ints, q: Ints, cos: Ints, sin: Ints) -> tuple[Ints, Ints]:
    """(i + jq) * (cos - j sin): shifts the signal down by the NCO frequency."""
    re = saturate(round_shift(i * cos + q * sin, MIX_SHIFT), MIX_BITS)
    im = saturate(round_shift(q * cos - i * sin, MIX_SHIFT), MIX_BITS)
    return re, im


def cic_decimate(x: Ints, reg_bits: int = CIC_REG_BITS) -> Ints:
    """Hogenauer CIC, CIC_ORDER stages, decimate by CIC_R, M = 1. Registers wrap; the output is still exact."""
    y = x
    for _ in range(CIC_ORDER):
        y = wrap(np.cumsum(y), reg_bits)
    y = y[CIC_R - 1 :: CIC_R]
    for _ in range(CIC_ORDER):
        y = wrap(np.diff(y, prepend=0), reg_bits)
    return saturate(round_shift(y, CIC_SHIFT), OUT_BITS)


def comp_taps(cfg: RxConfig) -> Ints:
    taps: Ints = np.round(comp_fir_taps(cfg) * (1 << COMP_FRAC)).astype(np.int64)
    return taps


def comp_fir(x: Ints, taps: Ints) -> Ints:
    acc = np.convolve(x, taps)[: x.size]
    return saturate(round_shift(acc, COMP_FRAC), OUT_BITS)


def ddc_fixed(raw: npt.NDArray[np.uint8], cfg: RxConfig) -> Complex:
    """Bit-true counterpart of receiver.ddc(); output scaled by 2^-15 so it can feed demodulate_baseband()."""
    i, q = ddc_fixed_rails(raw, cfg)
    out: Complex = ((i + 1j * q) / (1 << (OUT_BITS - 1))).astype(np.complex128)
    return out


def ddc_fixed_rails(raw: npt.NDArray[np.uint8], cfg: RxConfig) -> tuple[Ints, Ints]:
    """The DDC's s16 I and Q output, as the RTL produces it."""
    if (cfg.decimation, cfg.cic_order) != (CIC_R, CIC_ORDER):
        raise ValueError("bit-true DDC is fixed at CIC /4, order 3 (ADR 0004)")
    i, q = ingest(raw)
    i, q = dc_block(i), dc_block(q)
    cos, sin = nco(i.size, freq_word(cfg.tune_offset_hz, cfg.fs))
    i, q = mix(i, q, cos, sin)
    taps = comp_taps(cfg)
    return comp_fir(cic_decimate(i), taps), comp_fir(cic_decimate(q), taps)
