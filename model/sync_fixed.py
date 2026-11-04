"""Bit-true synchronization: AGC -> Costas -> Farrow + per-rail Gardner (CLAUDE.md §8.1 item 2, ADR 0002).

Input is the RRC output (model/rrc_fixed.py). Same conventions as model/ddc_fixed.py: round-half-up, explicit
saturation on every narrowing. Formats are in docs/fixed-point.md. Loop gains are computed from the same RxConfig
values the float receiver uses; in the RTL they are control registers the host writes.

The coarse frequency estimate is not here: per ADR 0002 the host computes it and adds it to the DDC NCO word
(see coarse_tune_hz()).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import numpy.typing as npt

from model.channel import SYMBOL_RATE
from model.ddc_fixed import LUT_PHASE_BITS, NCO_BITS, PHASE_BITS, Ints, ddc_fixed_rails, nco
from model.receiver import RxConfig, coarse_frequency, normalize_rails
from model.rrc_fixed import ddc_rrc_fixed, rrc_fixed

ONE = 1 << 12  # sync-domain unit: AGC output rail rms 1.0 = 4096, so 8x rms headroom in s16
SYNC_BITS = 16
AGC_FRAC = 12  # gain format u20 with 12 fraction bits: 1/4096 to 256
AGC_GAIN_BITS = 20
AGC_SHIFT = 24  # loop gain 2^(12-24) per sample at gain 4: time constant ~4096 samples (16 ms)
AGC_TARGET = 2 * ONE * ONE  # I^2 + Q^2 = 2: unit power per rail, what receiver.normalize_rails() gives
FREQ_FRAC = 16  # extra fraction bits under the 32-bit phase LSB in the Costas frequency integrator
MU_BITS = 16  # Farrow fractional delay
POS_FRAC = 24  # timing position, fraction bits of an input sample
INTEG_FRAC = 16  # extra fraction bits in the timing integrator
TWO_PI = 1 << PHASE_BITS


@dataclass(frozen=True)
class LoopGains:
    """Integer loop registers derived from the float configuration."""

    costas_kp: int
    costas_ki: int  # FREQ_FRAC extra fraction bits
    costas_max: int  # FREQ_FRAC extra fraction bits
    timing_nominal: int  # POS_FRAC
    timing_kp: int  # POS_FRAC per ONE of error
    timing_ki: int  # POS_FRAC + INTEG_FRAC per ONE of error
    timing_limit: int  # POS_FRAC + INTEG_FRAC


def loop_gains(cfg: RxConfig) -> LoopGains:
    fs2 = cfg.fs / cfg.decimation
    bw = cfg.costas_bw
    denom = 1.0 + 2 * 0.707 * bw + bw * bw  # same filter as receiver.costas()
    alpha, beta = 4 * 0.707 * bw / denom, 4 * bw * bw / denom
    rad = TWO_PI / (2 * np.pi) / ONE  # phase LSBs per rad, per ONE of error
    nominal = fs2 / SYMBOL_RATE / 2.0
    return LoopGains(
        costas_kp=round(alpha * rad),
        costas_ki=round(beta * rad * (1 << FREQ_FRAC)),
        costas_max=round(2 * np.pi * cfg.costas_max_hz / fs2 * TWO_PI / (2 * np.pi) * (1 << FREQ_FRAC)),
        timing_nominal=round(nominal * (1 << POS_FRAC)),
        timing_kp=round(cfg.timing_kp * (1 << POS_FRAC) / ONE),
        timing_ki=round(cfg.timing_ki * (1 << (POS_FRAC + INTEG_FRAC)) / ONE),
        timing_limit=round(nominal * 0.01 * (1 << (POS_FRAC + INTEG_FRAC))),
    )


def agc(i: Ints, q: Ints, gain0: int = 1 << AGC_FRAC) -> tuple[Ints, Ints, Ints]:
    """Feedback AGC on I^2 + Q^2. Returns (I, Q, gain). The gain update uses the output it just produced."""
    lo, hi = -(1 << (SYNC_BITS - 1)), (1 << (SYNC_BITS - 1)) - 1
    gmax = (1 << AGC_GAIN_BITS) - 1
    half_a, half_s = 1 << (AGC_FRAC - 1), 1 << (AGC_SHIFT - 1)
    g = gain0
    out_i, out_q, gains = [0] * i.size, [0] * i.size, [0] * i.size
    for n, (a, b) in enumerate(zip(i.tolist(), q.tolist(), strict=True)):
        yi = min(max((a * g + half_a) >> AGC_FRAC, lo), hi)
        yq = min(max((b * g + half_a) >> AGC_FRAC, lo), hi)
        out_i[n], out_q[n], gains[n] = yi, yq, g
        g = min(max(g + ((AGC_TARGET - yi * yi - yq * yq + half_s) >> AGC_SHIFT), 1), gmax)
    return np.array(out_i), np.array(out_q), np.array(gains)


def _phasor_table() -> tuple[list[int], list[int]]:
    """cos/sin for every 12-bit table phase: the DDC's quarter-wave NCO, read at each phase once."""
    size = 1 << LUT_PHASE_BITS
    cos, sin = nco(size, 1 << (PHASE_BITS - LUT_PHASE_BITS))
    return cos.tolist(), sin.tolist()


def costas(i: Ints, q: Ints, gains: LoopGains) -> tuple[Ints, Ints, Ints]:
    """Fourth-order Costas loop, every sample. Returns (I, Q, frequency in phase LSBs/sample, FREQ_FRAC bits)."""
    cos_t, sin_t = _phasor_table()
    lo, hi = -(1 << (SYNC_BITS - 1)), (1 << (SYNC_BITS - 1)) - 1
    s, half = NCO_BITS - 1, 1 << (NCO_BITS - 2)
    table_shift = PHASE_BITS - LUT_PHASE_BITS
    mask = TWO_PI - 1
    phase, freq = 0, 0
    out_i, out_q, track = [0] * i.size, [0] * i.size, [0] * i.size
    for n, (a, b) in enumerate(zip(i.tolist(), q.tolist(), strict=True)):
        c, sn = cos_t[phase >> table_shift], sin_t[phase >> table_shift]
        yi = min(max((a * c + b * sn + half) >> s, lo), hi)
        yq = min(max((b * c - a * sn + half) >> s, lo), hi)
        out_i[n], out_q[n] = yi, yq
        err = (yq if yi > 0 else -yq) - (yi if yq > 0 else -yi)
        err = min(max(err, -ONE), ONE)
        freq = min(max(freq + gains.costas_ki * err, -gains.costas_max), gains.costas_max)
        phase = (phase + (freq >> FREQ_FRAC) + gains.costas_kp * err) & mask
        track[n] = freq
    return np.array(out_i), np.array(out_q), np.array(track)


def farrow(p0: int, p1: int, p2: int, p3: int, mu: int) -> int:
    """Catmull-Rom cubic between p1 and p2, mu in [0, 1) with MU_BITS fraction bits. Horner form, as the RTL."""
    c1 = p2 - p0
    c2 = 2 * p0 - 5 * p1 + 4 * p2 - p3
    c3 = 3 * (p1 - p2) + p3 - p0
    half = 1 << (MU_BITS - 1)
    v = (c3 * mu + half) >> MU_BITS
    v = ((v + c2) * mu + half) >> MU_BITS
    v = ((v + c1) * mu + half) >> MU_BITS
    return min(max(p1 + ((v + 1) >> 1), -(1 << (SYNC_BITS - 1))), (1 << (SYNC_BITS - 1)) - 1)


def timing(i: Ints, q: Ints, gains: LoopGains) -> tuple[Ints, Ints]:
    """Farrow resampler to 2 sps with the per-rail Gardner detector of receiver.oqpsk_timing()."""
    re, im = i.tolist(), q.tolist()
    last = len(re) - 3
    out_re: list[int] = []
    out_im: list[int] = []
    pos, integ, n = 1 << POS_FRAC, 0, 0
    frac_mask = (1 << POS_FRAC) - 1
    half_e = 1 << 11
    while (pos >> POS_FRAC) < last:
        k = pos >> POS_FRAC
        mu = (pos & frac_mask) >> (POS_FRAC - MU_BITS)
        out_re.append(farrow(re[k - 1], re[k], re[k + 1], re[k + 2], mu))
        out_im.append(farrow(im[k - 1], im[k], im[k + 1], im[k + 2], mu))
        err = 0
        if n >= 2:
            rail = out_re if n % 2 == 0 else out_im
            err = (rail[n - 1] * (rail[n - 2] - rail[n]) + half_e) >> 12  # product of two ONE-scaled values
            err = min(max(err, -ONE), ONE)
        integ = min(max(integ + gains.timing_ki * err, -gains.timing_limit), gains.timing_limit)
        pos += gains.timing_nominal + (integ >> INTEG_FRAC) + gains.timing_kp * err
        n += 1
    return np.array(out_re, dtype=np.int64), np.array(out_im, dtype=np.int64)


def serial(i: Ints, q: Ints) -> Ints:
    """re[0], im[1], re[2], im[3], ...: the serial soft stream of receiver.serial_soft(), unnormalized."""
    out: Ints = q.copy()
    out[0::2] = i[0::2]
    return out


def coarse_tune_hz(raw: npt.NDArray[np.uint8], cfg: RxConfig) -> float:
    """Host side (ADR 0002): estimate the carrier offset from the bit-true RRC output; return the corrected NCO."""
    offset = coarse_frequency(normalize_rails(ddc_rrc_fixed(raw, cfg)), cfg.fs / cfg.decimation, cfg)
    return cfg.tune_offset_hz + offset


def demodulate_fixed(raw: npt.NDArray[np.uint8], cfg: RxConfig) -> tuple[Ints, Ints, float]:
    """cu8 -> serial soft stream, all bit-true. Returns (soft, Costas frequency track, NCO tune in Hz)."""
    tuned = replace(cfg, tune_offset_hz=coarse_tune_hz(raw, cfg))
    i, q = rrc_fixed(*ddc_fixed_rails(raw, tuned), tuned)
    i, q, _ = agc(i, q)
    gains = loop_gains(tuned)
    i, q, freq = costas(i, q, gains)
    i, q = timing(i, q, gains)
    return serial(i, q), freq, tuned.tune_offset_hz


def freq_hz(track: Ints, cfg: RxConfig) -> npt.NDArray[np.float64]:
    """Costas frequency register -> Hz at the RRC rate."""
    out: npt.NDArray[np.float64] = track / (1 << FREQ_FRAC) / TWO_PI * (cfg.fs / cfg.decimation)
    return out
