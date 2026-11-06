"""Lock time and lock range of the bit-true sync chain, which the RTL matches bit for bit (test_sync_top.py).

Two sweeps, both from reset (AGC from gain 1.0, loops from zero), at 6 dB Eb/N0 with a 30 Hz/s Doppler ramp, about
the physical maximum (sync_fixed_study.RAMP_HZ_S):
- sync_lock_costas: the carrier loop's own pull-in. The DDC is tuned with a known residual error and no coarse
  estimate, as if the host's estimate had missed by that much.
- sync_lock_range: the whole receiver, host coarse estimate (ADR 0002) included, across carrier offsets.
- sync_doppler_track: one longer run through the steepest part of a pass, falling at 30 Hz/s as at closest approach:
  the true carrier against the receiver's estimate (NCO tune + Costas register), every 5 ms.

Lock: the Costas frequency register, averaged over 10 ms, stays within LOCK_HZ of the true residual frequency from
then to the end of the run. Writes data/results/sync_lock_{costas,range}.csv, sync_doppler_track.csv.
Run: python -m analysis.sync_lock_study
"""

from __future__ import annotations

from dataclasses import replace
from multiprocessing import Pool

import numpy as np
import numpy.typing as npt

from analysis.common import write_result
from analysis.ddc_fixed_study import TUNE_HZ
from analysis.sync_fixed_study import RAMP_HZ_S
from model.channel import TxConfig, apply_carrier, awgn, modulate, noise_sigma, to_cu8
from model.coding import build_cadus, encode_stream
from model.ddc_fixed import ddc_fixed_rails
from model.receiver import RxConfig, data_bytes, decode_soft
from model.rrc_fixed import rrc_fixed
from model.sync_fixed import agc, coarse_tune_hz, costas, freq_hz, loop_gains, serial, timing

EBN0_DB = 6.0
FRAMES = 12  # 1.37 s (0.114 s per frame): the coarse estimator gets its full 1 s window, as on a pass
LOCK_HZ = 10.0  # tracking error is 2-4 Hz rms at 2-8 dB (sync_fixed_chain.csv)
AVG_S = 0.01
SEEDS = range(1, 5)
RESIDUALS_HZ = (-100.0, -50.0, 0.0, 25.0, 50.0, 75.0, 100.0, 150.0, 200.0, 300.0)
TRACK_FRAMES = 40  # 4.6 s
TRACK_START_HZ = 70.0  # crosses zero mid-run, as at closest approach
TRACK_STEP_S = 0.005
OFFSETS_HZ = (-20_000.0, -15_000.0, -8_000.0, -3_400.0, 0.0, 1_000.0, 3_400.0, 8_000.0, 14_000.0, 16_000.0)


def raw_signal(
    offset_hz: float, seed: int, frames: int = FRAMES, ramp: float = RAMP_HZ_S, ebn0_db: float = EBN0_DB
) -> tuple[npt.NDArray[np.uint8], set[bytes], float]:
    """cu8 capture tuned TUNE_HZ off a carrier at offset_hz + ramp; returns (raw, sent frames, sample rate)."""
    tx = TxConfig(timing_offset_sym=0.37, clock_ppm=20.0)
    plain, on_air = build_cadus(frames, seed)
    x = apply_carrier(modulate(encode_stream(on_air), tx), tx.fs, TUNE_HZ + offset_hz, ramp, 0.7)
    sigma = noise_sigma(ebn0_db, tx.fs)
    return to_cu8(awgn(x, sigma, seed), full_scale=4 * sigma), {bytes(p) for p in data_bytes(plain)}, tx.fs


def run_chain(raw: npt.NDArray[np.uint8], cfg: RxConfig) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.float64]]:
    """Bit-true DDC -> RRC -> AGC -> Costas -> timing at cfg's NCO tune. Returns (serial soft, Costas Hz track)."""
    i, q = rrc_fixed(*ddc_fixed_rails(raw, cfg), cfg)
    i, q, _ = agc(i, q)
    gains = loop_gains(cfg)
    i, q, track = costas(i, q, gains)
    return serial(*timing(i, q, gains)), freq_hz(track, cfg)


def lock_time_s(track_hz: npt.NDArray[np.float64], truth_hz: npt.NDArray[np.float64], fs2: float) -> float:
    """First time after which the 10 ms average stays within LOCK_HZ of truth; nan if it never does."""
    width = int(AVG_S * fs2)
    kernel = np.ones(width) / width
    err = np.convolve(track_hz, kernel, mode="valid") - np.convolve(truth_hz, kernel, mode="valid")
    outside = np.flatnonzero(np.abs(err) > LOCK_HZ)
    if outside.size == 0:
        return 0.0
    if outside[-1] >= err.size - 1:
        return float("nan")
    return float(outside[-1] + width) / fs2  # end of the last window outside


def frames_good(soft: npt.NDArray[np.int64], cfg: RxConfig, truth: set[bytes]) -> int:
    s = soft.astype(float)
    return sum(bytes(c) in truth for c in data_bytes(decode_soft(s / np.mean(np.abs(s)), cfg).cadus))


def _costas_case(args: tuple[float, int]) -> list[object]:
    residual, seed = args
    raw, truth, fs = raw_signal(residual, seed)
    cfg = RxConfig(fs=fs, tune_offset_hz=TUNE_HZ)
    soft, track = run_chain(raw, cfg)
    fs2 = fs / cfg.decimation
    expect = residual + RAMP_HZ_S * np.arange(track.size) / fs2
    lock = lock_time_s(track, expect, fs2)
    return [residual, seed, f"{raw.size / 2 / fs:.2f}", f"{lock:.3f}", frames_good(soft, cfg, truth), FRAMES]


def _range_case(args: tuple[float, int]) -> list[object]:
    offset, seed = args
    raw, truth, fs = raw_signal(offset, seed)
    base = RxConfig(fs=fs, tune_offset_hz=TUNE_HZ)
    cfg = replace(base, tune_offset_hz=coarse_tune_hz(raw, base))
    soft, track = run_chain(raw, cfg)
    fs2 = fs / cfg.decimation
    residual = offset - (cfg.tune_offset_hz - TUNE_HZ)  # what the coarse estimate left for the Costas loop
    expect = residual + RAMP_HZ_S * np.arange(track.size) / fs2
    lock = lock_time_s(track, expect, fs2)
    return [offset, seed, f"{residual:.1f}", f"{lock:.3f}", frames_good(soft, cfg, truth), FRAMES]


def doppler_track() -> tuple[list[list[object]], int]:
    raw, truth, fs = raw_signal(TRACK_START_HZ, 1, TRACK_FRAMES, -RAMP_HZ_S)
    base = RxConfig(fs=fs, tune_offset_hz=TUNE_HZ)
    cfg = replace(base, tune_offset_hz=coarse_tune_hz(raw, base))
    soft, track = run_chain(raw, cfg)
    fs2 = fs / cfg.decimation
    width = int(AVG_S * fs2)
    est = cfg.tune_offset_hz - TUNE_HZ + np.convolve(track, np.ones(width) / width, mode="valid")
    t = (np.arange(est.size) + width / 2) / fs2  # centre of each averaging window
    true = TRACK_START_HZ - RAMP_HZ_S * t
    step = int(TRACK_STEP_S * fs2)
    rows: list[list[object]] = [
        [f"{t[k]:.3f}", f"{true[k]:.1f}", f"{est[k]:.1f}", f"{est[k] - true[k]:.2f}"] for k in range(0, t.size, step)
    ]
    return rows, frames_good(soft, cfg, truth)


def main() -> None:
    note = (
        f"seeds 1 to 4, {EBN0_DB} dB Eb/N0, {RAMP_HZ_S} Hz/s ramp, 0.37-symbol timing offset, 20 ppm clock; "
        f"bit-true chain from reset. Lock is within {LOCK_HZ} Hz ({AVG_S * 1000:.0f} ms average) of the true "
        "residual to the end of the run, timed from reset; nan means no lock"
    )
    with Pool() as pool:
        rows = pool.map(_costas_case, [(r, s) for r in RESIDUALS_HZ for s in SEEDS])
        write_result(
            "sync_lock_costas",
            ["residual_hz", "seed", "duration_s", "lock_time_s", "frames_good", "frames_sent"],
            rows,
            note + "; no coarse estimate, the DDC tuned residual_hz off the carrier",
        )
        rows = pool.map(_range_case, [(o, s) for o in OFFSETS_HZ for s in SEEDS])
        write_result(
            "sync_lock_range",
            ["offset_hz", "seed", "residual_hz", "lock_time_s", "frames_good", "frames_sent"],
            rows,
            note + "; host coarse estimate (coarse_tune_hz) on the whole capture, then the chain from reset",
        )
    rows, good = doppler_track()
    write_result(
        "sync_doppler_track",
        ["time_s", "true_hz", "estimate_hz", "error_hz"],
        rows,
        f"seed 1, {TRACK_FRAMES} frames, {EBN0_DB} dB Eb/N0, carrier from {TRACK_START_HZ:.0f} Hz falling at "
        f"{RAMP_HZ_S} Hz/s; estimate = NCO tune (host coarse estimate) + Costas register, {AVG_S * 1000:.0f} ms "
        f"average; bit-true chain from reset; {good} of {TRACK_FRAMES} frames decoded",
    )


if __name__ == "__main__":
    main()
