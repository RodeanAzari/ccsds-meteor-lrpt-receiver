"""Bit-true RRC: each format choice has a reason; these tests fail if the reason stops holding."""

from __future__ import annotations

import numpy as np

from model.channel import TxConfig, apply_carrier, awgn, modulate, noise_sigma, to_cu8
from model.coding import build_cadus, encode_stream
from model.ddc_fixed import ddc_fixed, ddc_fixed_rails
from model.receiver import RxConfig, data_bytes, decode_soft, demodulate_baseband, demodulate_filtered, rrc_taps
from model.rrc_fixed import OUT_BITS, RRC_FRAC, ddc_rrc_fixed, rrc_fixed, taps

SEED = 7
CFG = RxConfig(fs=1_024_000.0, tune_offset_hz=150_000.0)
DDC_PEAK = 22_900  # worst-case comp FIR output, docs/fixed-point.md


def test_taps_fit_the_dsp_port_and_stay_symmetric() -> None:
    # Symmetry lets the RTL halve its multipliers with the DSP48E1 pre-adder; 18 bits is the B port.
    h = taps(CFG)
    assert np.array_equal(h, h[::-1])
    assert np.abs(h).max() < 1 << RRC_FRAC
    assert abs(h.sum() / (1 << RRC_FRAC) - 1.0) < 1e-3  # unity DC gain: no level change into the loops


def test_worst_case_ddc_output_cannot_saturate_the_rrc() -> None:
    # fixed-point.md claims s16 out cannot clip. The worst input is the DDC's peak with the sign of each tap.
    h = taps(CFG)
    x = (DDC_PEAK * np.sign(h[::-1])).astype(np.int64)
    exact = (int(np.dot(x, h[::-1])) + (1 << (RRC_FRAC - 1))) >> RRC_FRAC
    y, _ = rrc_fixed(x, x, CFG)
    assert y[-1] == exact < (1 << (OUT_BITS - 1)) - 1


def test_quantization_noise_is_far_below_the_8_bit_input() -> None:
    # The RRC sits after 51 dB of DDC SQNR; it must add noise well under that, or it would cost soft-symbol SNR.
    rng = np.random.default_rng(SEED)
    x = np.round(rng.normal(0, 2000, 50_000)).astype(np.int64)
    y, _ = rrc_fixed(x, x, CFG)
    ref = np.convolve(x, rrc_taps(CFG.fs / CFG.decimation, CFG.rrc_span))[: x.size]
    sqnr = 10 * np.log10(np.sum(ref**2) / np.sum((y - ref) ** 2))
    assert sqnr > 60.0


def test_bit_true_rrc_costs_no_frames_and_no_soft_snr() -> None:
    # The widths are justified only if the decoder can't tell the bit-true RRC from the float one.
    tx = TxConfig(timing_offset_sym=0.37, clock_ppm=20.0)
    plain, on_air = build_cadus(6, SEED)
    sigma = noise_sigma(3.0, tx.fs)
    x = awgn(apply_carrier(modulate(encode_stream(on_air), tx), tx.fs, 151_000.0, 30.0, 0.7), sigma, SEED)
    raw = to_cu8(x, full_scale=4 * sigma)
    truth = {bytes(p) for p in data_bytes(plain)}
    outcome = []
    for soft in (
        demodulate_baseband(ddc_fixed(raw, CFG), CFG)[0],
        demodulate_filtered(ddc_rrc_fixed(raw, CFG), CFG)[0],
    ):
        a = np.abs(soft[soft.size // 10 :])
        good = sum(bytes(c) in truth for c in data_bytes(decode_soft(soft, CFG).cadus))
        outcome.append((good, 10 * np.log10(np.mean(a) ** 2 / np.var(a))))
    assert outcome[1][0] == outcome[0][0] >= 4
    assert abs(outcome[1][1] - outcome[0][1]) < 0.1
    assert ddc_fixed_rails(raw, CFG)[0].dtype == np.int64  # the RTL-facing path stays integer
