"""Bit-true sync loops: each format choice has a reason; these tests fail if the reason stops holding."""

from __future__ import annotations

import numpy as np

from model.channel import TxConfig, apply_carrier, awgn, modulate, noise_sigma, to_cu8
from model.coding import build_cadus, encode_stream
from model.receiver import RxConfig, _cubic, data_bytes, decode_soft, demodulate, ingest_cu8
from model.sync_fixed import (
    FREQ_FRAC,
    INTEG_FRAC,
    MU_BITS,
    ONE,
    POS_FRAC,
    TWO_PI,
    agc,
    demodulate_fixed,
    farrow,
    freq_hz,
    loop_gains,
)

SEED = 11
CFG = RxConfig(fs=1_024_000.0, tune_offset_hz=150_000.0)


def test_agc_output_level_does_not_depend_on_input_level() -> None:
    # Loop gains and soft-bit scaling assume unit rail power. Two inputs 20 dB apart must settle to the same level.
    rng = np.random.default_rng(SEED)
    for rms in (200.0, 2000.0):
        i, q = (np.round(rng.normal(0, rms, 200_000)).astype(np.int64) for _ in range(2))
        yi, yq, _ = agc(i, q)
        power = np.mean(yi[100_000:].astype(float) ** 2 + yq[100_000:].astype(float) ** 2) / (2 * ONE * ONE)
        assert abs(10 * np.log10(power)) < 0.2


def test_integer_loop_gains_keep_the_float_bandwidths() -> None:
    # A gain register too narrow rounds the gain away (a ki of 0 or 1 LSB is a different loop). Each integer gain
    # must reproduce the float gain the bandwidth sweeps chose, within 1%.
    g = loop_gains(CFG)
    bw = CFG.costas_bw
    denom = 1.0 + 2 * 0.707 * bw + bw * bw
    rad = TWO_PI / (2 * np.pi) / ONE
    pairs = [
        (g.costas_kp, 4 * 0.707 * bw / denom * rad),
        (g.costas_ki / (1 << FREQ_FRAC), 4 * bw * bw / denom * rad),
        (g.timing_kp, CFG.timing_kp * (1 << POS_FRAC) / ONE),
        (g.timing_ki / (1 << INTEG_FRAC), CFG.timing_ki * (1 << POS_FRAC) / ONE),
    ]
    for got, want in pairs:
        assert abs(got / want - 1) < 0.01


def test_farrow_matches_the_float_cubic_within_its_rounding_bound() -> None:
    # The RTL's Horner form rounds three times inside (each <= 1/2, scaled by mu <= 1, then halved: <= 3/4) and once
    # at the output (1/2): 1.25 LSB, -72 dB under rail rms. More than that means a wrong coefficient or shift.
    # At mu = 0 it must return the sample itself, or every on-time strobe is biased.
    rng = np.random.default_rng(SEED)
    for _ in range(5000):
        p0, p1, p2, p3 = (int(v) for v in rng.integers(-4 * ONE, 4 * ONE, 4))  # +-4x rail rms after the AGC
        mu = int(rng.integers(0, 1 << MU_BITS))
        assert abs(farrow(p0, p1, p2, p3, mu) - _cubic(p0, p1, p2, p3, mu / (1 << MU_BITS))) <= 1.25
        assert farrow(p0, p1, p2, p3, 0) == p1


def test_bit_true_sync_decodes_like_float_and_tracks_the_doppler_ramp() -> None:
    # The widths are justified only if the decoder can't tell bit-true sync from float. The NCO + Costas frequency
    # must also follow the applied ramp: that is what keeps lock through a pass.
    tx = TxConfig(timing_offset_sym=0.37, clock_ppm=20.0)
    plain, on_air = build_cadus(6, SEED)
    sigma = noise_sigma(3.0, tx.fs)
    clean = modulate(encode_stream(on_air), tx)
    ramp = 30.0
    raw = to_cu8(awgn(apply_carrier(clean, tx.fs, 151_000.0, ramp, 0.7), sigma, SEED), full_scale=4 * sigma)
    truth = {bytes(p) for p in data_bytes(plain)}
    float_soft = demodulate(ingest_cu8(raw), CFG)[0]
    soft, track, tune = demodulate_fixed(raw, CFG)
    outcome = []
    for s in (float_soft, soft / np.mean(np.abs(soft))):
        a = np.abs(s[s.size // 10 :])
        good = sum(bytes(c) in truth for c in data_bytes(decode_soft(s, CFG).cadus))
        outcome.append((good, 10 * np.log10(np.mean(a) ** 2 / np.var(a))))
    assert outcome[1][0] == outcome[0][0] >= 4
    assert abs(outcome[1][1] - outcome[0][1]) < 0.1
    end_hz = 1000.0 + ramp * clean.size / tx.fs
    assert abs(tune - 150_000.0 + freq_hz(track, CFG)[-1] - end_hz) < 10.0
