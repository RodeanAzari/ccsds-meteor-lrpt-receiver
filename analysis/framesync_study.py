"""Causal bit-true frame sync (model/framesync_fixed.py, the RTL's behaviour) against the float reference.

Both run on the same bit-true sync-chain output (sync_lock_study.run_chain, = the RTL) and their frames go through the
same back end (receiver.decode_frames). Writes data/results/framesync_fixed.csv. Run: python -m analysis.framesync_study
"""

from __future__ import annotations

from dataclasses import replace
from multiprocessing import Pool

import numpy as np

from analysis.common import write_result
from analysis.ddc_fixed_study import TUNE_HZ
from analysis.sync_lock_study import raw_signal, run_chain
from model.framesync_fixed import frame_sync_fixed
from model.receiver import RxConfig, data_bytes, decode_frames, frame_sync
from model.sync_fixed import coarse_tune_hz
from model.viterbi_fixed import quantize

FRAMES = 30
EBN0_DB = (1.5, 2.0, 2.5, 3.0, 4.0)
SEEDS = range(1, 4)


def _case(args: tuple[float, int]) -> list[object]:
    ebn0, seed = args
    raw, truth, fs = raw_signal(1000.0, seed, frames=FRAMES, ebn0_db=ebn0)
    base = RxConfig(fs=fs, tune_offset_hz=TUNE_HZ)
    cfg = replace(base, tune_offset_hz=coarse_tune_hz(raw, base))
    soft, _ = run_chain(raw, cfg)
    s = soft.astype(float) / np.mean(np.abs(soft))
    ref = frame_sync(s, cfg.sync_threshold, cfg.flywheel)
    fixed = frame_sync_fixed(quantize(soft, 4, 10), round(cfg.sync_threshold * 64), cfg.flywheel)
    row: list[object] = [ebn0, seed, FRAMES]
    for frames in (ref, fixed.frames):
        cadus = data_bytes(decode_frames(s, frames, cfg).cadus)
        row += [len(frames), sum(bytes(c) in truth for c in cadus)]
    return [*row, sum(fixed.flywheel), fixed.slips, fixed.dropped, sorted(ref) == sorted(fixed.frames)]


def main() -> None:
    with Pool() as pool:
        rows = pool.map(_case, [(e, s) for e in EBN0_DB for s in SEEDS])
    write_result(
        "framesync_fixed",
        ["ebn0_db", "seed", "frames_sent", "float_frames", "float_good", "fixed_frames", "fixed_good",
         "fixed_flywheel", "fixed_slips", "fixed_dropped", "same_frames"],
        rows,
        f"seeds 1 to 3, {FRAMES} frames, 1 kHz offset + 30 Hz/s, 0.37-symbol timing offset, 20 ppm clock; host "
        "coarse estimate, bit-true chain from reset; threshold 0.75 (48/64), flywheel 4, 4-candidate queue",
    )


if __name__ == "__main__":
    main()
