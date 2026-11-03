"""OQPSK modulator and channel model (CLAUDE.md §8.1). Seeded and deterministic."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from model.coding import Bits

Floats = npt.NDArray[np.float64]
Complex = npt.NDArray[np.complex128]

SYMBOL_RATE = 72_000.0  # signal-spec.md
RRC_ALPHA = 0.5  # signal-spec.md


def rrc(t: Floats, alpha: float = RRC_ALPHA) -> Floats:
    """RRC pulse with t in symbols, scaled so the pulse energy is one symbol period."""
    t = np.asarray(t, dtype=np.float64)
    out = np.zeros_like(t)
    singular = np.isclose(np.abs(t), 1.0 / (4.0 * alpha))
    centre = np.isclose(t, 0.0)
    regular = ~(singular | centre)
    tr = t[regular]
    numer = np.sin(np.pi * tr * (1 - alpha)) + 4 * alpha * tr * np.cos(np.pi * tr * (1 + alpha))
    out[regular] = numer / (np.pi * tr * (1 - (4 * alpha * tr) ** 2))
    out[centre] = 1 - alpha + 4 * alpha / np.pi
    a = np.pi / (4 * alpha)
    out[singular] = (alpha / np.sqrt(2)) * ((1 + 2 / np.pi) * np.sin(a) + (1 - 2 / np.pi) * np.cos(a))
    return out


def _shape(symbols: Floats, t_sym: Floats, alpha: float, span: int) -> Floats:
    idx = np.floor(t_sym).astype(np.int64)
    out = np.zeros_like(t_sym)
    for offset in range(-span + 1, span + 1):
        k = idx + offset
        valid = (k >= 0) & (k < symbols.size)
        out[valid] += symbols[k[valid]] * rrc(t_sym[valid] - k[valid], alpha)
    return out


@dataclass(frozen=True)
class TxConfig:
    """On-air options. Rail order is open in signal-spec.md, so both are selectable."""

    fs: float = 1_024_000.0
    q_leads: bool = False
    swap_rails: bool = False
    timing_offset_sym: float = 0.0
    clock_ppm: float = 0.0
    span: int = 8


def modulate(coded: Bits, cfg: TxConfig = TxConfig()) -> Complex:
    """Map coded symbols to OQPSK. Bit 1 maps to +1, matching SatDump's soft polarity."""
    pairs = coded.size // 2
    first = 2.0 * coded[0 : 2 * pairs : 2].astype(np.float64) - 1.0
    second = 2.0 * coded[1 : 2 * pairs : 2].astype(np.float64) - 1.0
    i_sym, q_sym = (second, first) if cfg.swap_rails else (first, second)
    sps = cfg.fs / SYMBOL_RATE
    n = int(np.ceil((pairs + 2) * sps))
    t = np.arange(n) / sps * (1.0 + cfg.clock_ppm * 1e-6) + cfg.timing_offset_sym
    q_delay = -0.5 if cfg.q_leads else 0.5
    i_wave = _shape(i_sym, t, RRC_ALPHA, cfg.span)
    q_wave = _shape(q_sym, t - q_delay, RRC_ALPHA, cfg.span)
    return i_wave + 1j * q_wave


def apply_carrier(
    x: Complex, fs: float, offset_hz: float = 0.0, ramp_hz_per_s: float = 0.0, phase_rad: float = 0.0
) -> Complex:
    t = np.arange(x.size) / fs
    return x * np.exp(1j * (2 * np.pi * (offset_hz * t + 0.5 * ramp_hz_per_s * t**2) + phase_rad))


def noise_sigma(ebn0_db: float, fs: float, code_rate: float = 0.5) -> float:
    """Per-rail noise standard deviation at sample rate `fs`, for modulate()'s unit-symbol-energy pulse."""
    ebn0 = 10.0 ** (ebn0_db / 10.0)
    return float(np.sqrt((fs / SYMBOL_RATE) / (2.0 * code_rate * ebn0)))


def awgn(x: Complex, sigma: float, seed: int) -> Complex:
    rng = np.random.default_rng(seed)
    return x + sigma * (rng.standard_normal(x.size) + 1j * rng.standard_normal(x.size))


def to_cu8(x: Complex, full_scale: float) -> npt.NDArray[np.uint8]:
    """Unsigned 8-bit interleaved I/Q, midpoint 127.5, the raw RTL-SDR format. `full_scale` maps to +-127.5."""
    out = np.empty(2 * x.size, dtype=np.float64)
    out[0::2] = x.real
    out[1::2] = x.imag
    return np.clip(np.round(out / full_scale * 127.5 + 127.5), 0, 255).astype(np.uint8)
