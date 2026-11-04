"""Bit-true sync (AGC, Costas, Farrow + Gardner) against float: frames, soft SNR and frequency tracking.

Writes data/results/sync_fixed_chain.csv and data/results/sync_agc_settle.csv. Run: python -m analysis.sync_fixed_study
"""

from __future__ import annotations

import numpy as np

from analysis.common import write_result
from analysis.ddc_fixed_study import FRAMES, SEED, TUNE_HZ, soft_snr_db
from model.channel import TxConfig, apply_carrier, awgn, modulate, noise_sigma, to_cu8
from model.coding import build_cadus, encode_stream
from model.ddc_fixed import ddc_fixed_rails
from model.receiver import RxConfig, data_bytes, decode_soft, demodulate, ingest_cu8
from model.rrc_fixed import rrc_fixed
from model.sync_fixed import AGC_FRAC, agc, demodulate_fixed, freq_hz

RAMP_HZ_S = 30.0  # about the physical maximum: 137.9 MHz * (7.5 km/s)^2 / (830 km * c) = 31 Hz/s


def main() -> None:
    tx = TxConfig(timing_offset_sym=0.37, clock_ppm=20.0)
    plain, on_air = build_cadus(FRAMES, SEED)
    clean = modulate(encode_stream(on_air), tx)
    cfg = RxConfig(fs=tx.fs, tune_offset_hz=TUNE_HZ)
    truth = {bytes(p) for p in data_bytes(plain)}
    rows = []
    agc_rows = []
    for offset in (1000.0, 3400.0):
        shifted = apply_carrier(clean, tx.fs, TUNE_HZ + offset, RAMP_HZ_S, 0.7)
        for ebn0 in [2.0, 2.5, 3.0, 4.0, 8.0]:
            sigma = noise_sigma(ebn0, tx.fs)
            raw = to_cu8(awgn(shifted, sigma, SEED), full_scale=4 * sigma)
            float_soft = demodulate(ingest_cu8(raw), cfg)[0]
            soft, track, tune = demodulate_fixed(raw, cfg)
            fixed_soft = soft / np.mean(np.abs(soft))
            row: list[object] = [offset, ebn0]
            for s in (float_soft, fixed_soft):
                good = sum(bytes(c) in truth for c in data_bytes(decode_soft(s, cfg).cadus))
                row += [round(soft_snr_db(s), 2), good]
            # Frequency tracking error over the second half, where both loops are past pull-in.
            t = np.arange(track.size) / (cfg.fs / cfg.decimation)
            err = tune - TUNE_HZ + freq_hz(track, cfg) - (offset + RAMP_HZ_S * t)
            row += [round(float(np.sqrt(np.mean(err[err.size // 2 :] ** 2))), 1), FRAMES]
            rows.append(row)
            print(row)
            if offset == 1000.0:
                _, _, gain = agc(*rrc_fixed(*ddc_fixed_rails(raw, cfg), cfg))
                settled = float(gain[gain.size // 2 :].mean())
                to_90 = int(np.argmax(gain > 0.9 * settled))
                agc_rows.append([ebn0, round(settled / (1 << AGC_FRAC), 2), to_90, round(to_90 / 256.0, 1)])
    write_result(
        "sync_fixed_chain",
        [
            "offset_hz",
            "ebn0_db",
            "soft_snr_float_db",
            "frames_float",
            "soft_snr_fixed_db",
            "frames_fixed",
            "freq_err_rms_hz",
            "frames",
        ],
        rows,
        seed=f"{SEED}; ramp {RAMP_HZ_S} Hz/s, 0.37-symbol timing offset, 20 ppm clock; float arm is the float chain",
    )
    write_result(
        "sync_agc_settle",
        ["ebn0_db", "settled_gain", "samples_to_90pct", "ms_to_90pct"],
        agc_rows,
        seed=f"{SEED}; AGC from gain 1.0 on the bit-true RRC output, before the coarse NCO correction",
    )


if __name__ == "__main__":
    main()
