"""Stimulus and bit-true reference for the sync chain tests (test_sync_top.py, test_sync_top_full.py).

The input is what sync_top sees in the receiver: OQPSK at 6 dB Eb/N0, 1 kHz off the tuning offset with a 30 Hz/s
ramp, 0.37 symbol late with a 20 ppm clock error, quantized to cu8, then the bit-true DDC tuned by the host's coarse
estimate (ADR 0002). The reference is the model chain rrc_fixed -> agc (from gain 1.0) -> costas -> timing.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from model import ddc_fixed, rrc_fixed, sync_fixed
from model.channel import TxConfig, apply_carrier, awgn, modulate, noise_sigma, to_cu8
from model.coding import build_cadus, encode_stream
from model.receiver import RxConfig, data_bytes

TUNE_HZ = 150_000.0
OFFSET_HZ = 1000.0
RAMP_HZ_S = 30.0


def ddc_input(frames: int, seed: int) -> tuple[np.ndarray, np.ndarray, RxConfig, set[bytes]]:
    """Bit-true DDC output (sync_top's input) of `frames` CADUs; the config carries the coarse-tuned NCO."""
    tx = TxConfig(timing_offset_sym=0.37, clock_ppm=20.0)
    plain, on_air = build_cadus(frames, seed)
    sigma = noise_sigma(6.0, tx.fs)
    x = awgn(apply_carrier(modulate(encode_stream(on_air), tx), tx.fs, TUNE_HZ + OFFSET_HZ, RAMP_HZ_S, 0.7),
             sigma, seed)
    raw = to_cu8(x, full_scale=4 * sigma)
    cfg = RxConfig(fs=tx.fs, tune_offset_hz=TUNE_HZ)
    tuned = replace(cfg, tune_offset_hz=sync_fixed.coarse_tune_hz(raw, cfg))
    i, q = ddc_fixed.ddc_fixed_rails(raw, tuned)
    return i, q, tuned, {bytes(p) for p in data_bytes(plain)}


def expected(i: np.ndarray, q: np.ndarray, cfg: RxConfig) -> tuple[np.ndarray, np.ndarray]:
    """What sync_top emits for this input. The model's timing() stops one sample before the stream does, so it gets
    one sample more (as in test_sync_timing.py)."""
    gains = sync_fixed.loop_gains(cfg)
    a, b = rrc_fixed.rrc_fixed(i, q, cfg)
    a, b, _ = sync_fixed.agc(a, b)
    a, b, _ = sync_fixed.costas(a, b, gains)
    return sync_fixed.timing(np.append(a, 0), np.append(b, 0), gains)


def set_gains(dut, cfg: RxConfig) -> None:
    g = sync_fixed.loop_gains(cfg)
    dut.costas_kp_i.value = g.costas_kp
    dut.costas_ki_i.value = g.costas_ki
    dut.costas_fmax_i.value = g.costas_max
    dut.timing_nominal_i.value = g.timing_nominal
    dut.timing_kp_i.value = g.timing_kp
    dut.timing_ki_i.value = g.timing_ki
    dut.timing_limit_i.value = g.timing_limit
