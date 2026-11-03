"""Bit-true DDC: each stage's width or rounding choice has a reason; these tests fail if the reason stops holding."""

from __future__ import annotations

import numpy as np
from scipy import signal

from model.channel import TxConfig, apply_carrier, awgn, modulate, noise_sigma, to_cu8
from model.coding import build_cadus, encode_stream
from model.ddc_fixed import (
    CIC_REG_BITS,
    CIC_SHIFT,
    LUT_PHASE_BITS,
    NCO_BITS,
    PHASE_BITS,
    cic_decimate,
    dc_block,
    ddc_fixed,
    freq_word,
    ingest,
    nco,
    round_shift,
)
from model.receiver import RxConfig, data_bytes, ddc, decode_soft, demodulate_baseband, ingest_cu8

SEED = 5


def test_ingest_is_symmetric_about_the_cu8_midpoint() -> None:
    # The RTL-SDR midpoint is 127.5. Mapping it to anything but zero adds a DC offset to every sample.
    i, q = ingest(np.array([0, 255, 127, 128], dtype=np.uint8))
    assert list(i) == [-255, -1] and list(q) == [255, 1]


def test_nco_quadrant_mirroring_matches_the_ideal_phasor() -> None:
    # Quarter-wave tables fail at quadrant boundaries (sign or index-reversal slips). Every output must equal
    # the rounded ideal phasor at the truncated phase, exactly.
    amp = (1 << (NCO_BITS - 1)) - 1
    for word in np.random.default_rng(SEED).integers(1, 1 << PHASE_BITS, 8):
        cos, sin = nco(1 << 14, int(word))
        p = ((np.arange(1 << 14) * int(word)) % (1 << PHASE_BITS)) >> (PHASE_BITS - LUT_PHASE_BITS)
        theta = 2 * np.pi * (p + 0.5) / (1 << LUT_PHASE_BITS)
        assert np.array_equal(cos, np.round(amp * np.cos(theta)))
        assert np.array_equal(sin, np.round(amp * np.sin(theta)))


def test_nco_spurs_sit_far_below_the_8_bit_input() -> None:
    # An 8-bit input has about 48 dB of dynamic range. NCO spurs must stay 12 dB under that, at any tuning
    # word, because Doppler pre-correction moves the word through the whole range during a pass.
    n = 1 << 16
    window = signal.windows.blackmanharris(n)
    for word in np.random.default_rng(SEED).integers(1, 1 << PHASE_BITS, 8):
        cos, sin = nco(n, int(word))
        spectrum = np.abs(np.fft.fft((cos + 1j * sin) * window)) ** 2
        peak = int(np.argmax(spectrum))
        spurs = np.delete(spectrum, np.arange(peak - 8, peak + 9) % n)
        assert 10 * np.log10(spectrum[peak] / spurs.max()) > 60.0


def _direct_cic(x: np.ndarray) -> np.ndarray:
    kernel = np.ones(1, dtype=np.int64)
    for _ in range(3):
        kernel = np.convolve(kernel, np.ones(4, dtype=np.int64))
    return round_shift(np.convolve(x, kernel)[: x.size][3::4], CIC_SHIFT)


def test_cic_is_exact_at_full_scale_although_its_integrators_wrap() -> None:
    # Integrators overflow by design; Hogenauer's register width makes the comb output exact anyway. An undersized
    # register wraps silently (CLAUDE.md §12), so the same input must break a register one bit short.
    x = np.concatenate([np.full(400, 32767), np.full(400, -32768), np.full(400, 32767)]).astype(np.int64)
    assert np.array_equal(cic_decimate(x), _direct_cic(x))
    assert not np.array_equal(cic_decimate(x, reg_bits=CIC_REG_BITS - 1), _direct_cic(x))


def test_dc_block_removes_rtl_sdr_offset_and_passes_the_signal() -> None:
    # The RTL-SDR adds a DC offset. It must go, without touching a tone at the tuning offset.
    n = np.arange(40_000)
    tone = np.round(100 * np.cos(2 * np.pi * 150_000 / 1_024_000 * n)).astype(np.int64)
    y = dc_block(tone + 20)[10_000:]  # skip about ten time constants
    assert abs(y.mean()) < 0.5
    assert abs(np.std(y) / np.std(tone) - 1) < 0.01


def test_bit_true_ddc_costs_no_frames_and_no_soft_snr() -> None:
    # The widths are justified only if the decoder can't tell the bit-true DDC from the float one.
    tx = TxConfig(timing_offset_sym=0.37, clock_ppm=20.0)
    plain, on_air = build_cadus(6, SEED)
    sigma = noise_sigma(3.0, tx.fs)
    x = awgn(apply_carrier(modulate(encode_stream(on_air), tx), tx.fs, 151_000.0, 30.0, 0.7), sigma, SEED)
    raw = to_cu8(x, full_scale=4 * sigma)
    cfg = RxConfig(fs=tx.fs, tune_offset_hz=150_000.0)
    truth = {bytes(p) for p in data_bytes(plain)}
    outcome = []
    for baseband in (ddc(ingest_cu8(raw), cfg), ddc_fixed(raw, cfg)):
        soft = demodulate_baseband(baseband, cfg)[0]
        a = np.abs(soft[soft.size // 10 :])
        good = sum(bytes(c) in truth for c in data_bytes(decode_soft(soft, cfg).cadus))
        outcome.append((good, 10 * np.log10(np.mean(a) ** 2 / np.var(a))))
    assert outcome[1][0] == outcome[0][0] >= 4
    assert abs(outcome[1][1] - outcome[0][1]) < 0.1
    assert freq_word(150_000.0, 1_024_000.0) == 600 << 20  # 150 kHz is exact in a 32-bit accumulator
