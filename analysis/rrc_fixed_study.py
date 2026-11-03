"""Bit-true RRC against float: RRC quantization noise, and what reaches the decoder.

Writes data/results/rrc_fixed_chain.csv. Run: python -m analysis.rrc_fixed_study
"""

from __future__ import annotations

import numpy as np

from analysis.common import write_result
from analysis.ddc_fixed_study import FRAMES, SEED, TUNE_HZ, soft_snr_db, sqnr_db
from model.channel import TxConfig, apply_carrier, awgn, modulate, noise_sigma, to_cu8
from model.coding import build_cadus, encode_stream
from model.ddc_fixed import ddc_fixed, ddc_fixed_rails
from model.receiver import RxConfig, data_bytes, decode_soft, demodulate_baseband, demodulate_filtered, rrc_taps
from model.rrc_fixed import ddc_rrc_fixed, rrc_fixed


def main() -> None:
    tx = TxConfig(timing_offset_sym=0.37, clock_ppm=20.0)
    plain, on_air = build_cadus(FRAMES, SEED)
    clean = apply_carrier(modulate(encode_stream(on_air), tx), tx.fs, TUNE_HZ + 1000.0, 30.0, 0.7)
    cfg = RxConfig(fs=tx.fs, tune_offset_hz=TUNE_HZ)
    h = rrc_taps(cfg.fs / cfg.decimation, cfg.rrc_span)
    truth = {bytes(p) for p in data_bytes(plain)}
    rows = []
    for ebn0 in [2.0, 2.5, 3.0, 4.0, 8.0, float("inf")]:
        sigma = noise_sigma(ebn0, tx.fs) if np.isfinite(ebn0) else noise_sigma(8.0, tx.fs)
        x = awgn(clean, sigma, SEED) if np.isfinite(ebn0) else clean
        raw = to_cu8(x, full_scale=4 * sigma)
        i, q = ddc_fixed_rails(raw, cfg)
        fi, fq = rrc_fixed(i, q, cfg)
        ref = np.convolve(i + 1j * q, h)[: i.size]  # same causal filter on the same integers, unquantized
        row: list[object] = [ebn0, round(sqnr_db(ref, fi + 1j * fq), 2)]
        float_rrc = demodulate_baseband(ddc_fixed(raw, cfg), cfg)[0]
        fixed_rrc = demodulate_filtered(ddc_rrc_fixed(raw, cfg), cfg)[0]
        for soft in (float_rrc, fixed_rrc):
            good = sum(bytes(c) in truth for c in data_bytes(decode_soft(soft, cfg).cadus))
            row += [round(soft_snr_db(soft), 2), good]
        rows.append([*row, FRAMES])
        print(rows[-1])
    write_result(
        "rrc_fixed_chain",
        [
            "ebn0_db",
            "rrc_sqnr_db",
            "soft_snr_float_rrc_db",
            "frames_float_rrc",
            "soft_snr_fixed_rrc_db",
            "frames_fixed_rrc",
            "frames",
        ],
        rows,
        seed=f"{SEED}; bit-true DDC on both arms; ebn0 inf = no noise, cu8 scaled as for 8 dB",
    )


if __name__ == "__main__":
    main()
