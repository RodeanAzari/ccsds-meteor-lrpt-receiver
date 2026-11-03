"""Bit-true DDC against float: NCO spurs, DDC quantization noise, and what reaches the decoder.

Writes data/results/ddc_nco_sfdr.csv and data/results/ddc_fixed_chain.csv. Run: python -m analysis.ddc_fixed_study
"""

from __future__ import annotations

import numpy as np
from scipy import signal

from analysis.common import write_result
from model.channel import Complex, TxConfig, apply_carrier, awgn, modulate, noise_sigma, to_cu8
from model.coding import build_cadus, encode_stream
from model.ddc_fixed import (
    CIC_ORDER,
    CIC_R,
    DC_K,
    MIX_SHIFT,
    NCO_BITS,
    PHASE_BITS,
    comp_fir_taps,
    ddc_fixed,
    freq_word,
    ingest,
    nco,
)
from model.receiver import RxConfig, data_bytes, ddc, decode_soft, demodulate_baseband, ingest_cu8

FS = 1_024_000.0
TUNE_HZ = 150_000.0  # make_synthetic_iq.py and CLAUDE.md §2.3
SEED = 2026
FRAMES = 20
NCO_FFT = 1 << 18
RANDOM_WORDS = 64


def sfdr_db(word: int) -> float:
    cos, sin = nco(NCO_FFT, word)
    spectrum = np.abs(np.fft.fft((cos + 1j * sin) * signal.windows.blackmanharris(NCO_FFT))) ** 2
    peak = int(np.argmax(spectrum))
    guard = np.arange(peak - 8, peak + 9) % NCO_FFT  # Blackman-Harris main lobe is 4 bins each side
    spurs = np.delete(spectrum, guard)
    return float(10 * np.log10(spectrum[peak] / spurs.max()))


def float_reference(raw: np.ndarray, cfg: RxConfig) -> Complex:
    """The bit-true structure in floating point: same causal filters, same delays, unquantized."""
    i, q = ingest(raw)
    x = i.astype(np.float64) + 1j * q.astype(np.float64)
    pole = 1.0 - 2.0**-DC_K
    x = signal.lfilter([1.0, -1.0], [1.0, -pole], x)
    n = np.arange(x.size)
    word = freq_word(cfg.tune_offset_hz, cfg.fs)
    x = x * np.exp(-2j * np.pi * (n * word % (1 << PHASE_BITS)) / (1 << PHASE_BITS))
    x = x * ((1 << (NCO_BITS - 1)) - 1) / (1 << MIX_SHIFT)
    kernel = np.ones(1)
    for _ in range(CIC_ORDER):
        kernel = np.convolve(kernel, np.ones(CIC_R) / CIC_R)
    x = np.convolve(x, kernel)[: x.size][CIC_R - 1 :: CIC_R]
    out: Complex = np.convolve(x, comp_fir_taps(cfg))[: x.size]
    return out


def sqnr_db(ref: Complex, got: Complex) -> float:
    gain = np.vdot(ref, got) / np.vdot(ref, ref)
    err = got - gain * ref
    return float(10 * np.log10(np.sum(np.abs(gain * ref) ** 2) / np.sum(np.abs(err) ** 2)))


def soft_snr_db(soft: np.ndarray) -> float:
    a = np.abs(soft[soft.size // 10 :])  # skip the loops' pull-in
    return float(10 * np.log10(np.mean(a) ** 2 / np.var(a)))


def main() -> None:
    words = [freq_word(TUNE_HZ, FS), *np.random.default_rng(SEED).integers(1, 1 << PHASE_BITS, RANDOM_WORDS)]
    sfdr = [(int(w), w * FS / (1 << PHASE_BITS), round(sfdr_db(int(w)), 2)) for w in words]
    write_result("ddc_nco_sfdr", ["freq_word", "freq_hz", "sfdr_db"], sfdr, seed=f"{SEED} (random words)")

    tx = TxConfig(timing_offset_sym=0.37, clock_ppm=20.0)
    plain, on_air = build_cadus(FRAMES, SEED)
    clean = apply_carrier(modulate(encode_stream(on_air), tx), tx.fs, TUNE_HZ + 1000.0, 30.0, 0.7)
    cfg = RxConfig(fs=tx.fs, tune_offset_hz=TUNE_HZ)
    truth = {bytes(p) for p in data_bytes(plain)}
    rows = []
    for ebn0 in [2.0, 2.5, 3.0, 4.0, 8.0, float("inf")]:
        sigma = noise_sigma(ebn0, tx.fs) if np.isfinite(ebn0) else noise_sigma(8.0, tx.fs)
        x = awgn(clean, sigma, SEED) if np.isfinite(ebn0) else clean
        raw = to_cu8(x, full_scale=4 * sigma)
        fixed = ddc_fixed(raw, cfg)
        ddc_sqnr = sqnr_db(float_reference(raw, cfg), fixed)
        row: list[object] = [ebn0, round(ddc_sqnr, 2)]
        for baseband in (ddc(ingest_cu8(raw), cfg), fixed):
            soft = demodulate_baseband(baseband, cfg)[0]
            result = decode_soft(soft, cfg)
            good = sum(bytes(c) in truth for c in data_bytes(result.cadus))
            row += [round(soft_snr_db(soft), 2), good]
        rows.append([*row, FRAMES])
        print(rows[-1])
    write_result(
        "ddc_fixed_chain",
        ["ebn0_db", "ddc_sqnr_db", "soft_snr_float_db", "frames_float", "soft_snr_fixed_db", "frames_fixed", "frames"],
        rows,
        seed=f"{SEED}; ebn0 inf = no noise, cu8 scaled as for 8 dB",
    )


if __name__ == "__main__":
    main()
