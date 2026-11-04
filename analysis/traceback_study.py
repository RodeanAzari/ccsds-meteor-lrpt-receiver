"""Traceback depth and start state: BER vs depth for the 4-bit decoder (ADR 0007).

One ACS run per batch feeds every depth, so all configurations see identical noise and decisions.
Writes data/results/traceback_depth.csv. Run: python -m analysis.traceback_study
"""

from __future__ import annotations

from multiprocessing import Pool

import numpy as np

from analysis.ber import MIN_ERRORS
from analysis.common import write_result
from model.coding import conv_encode
from model.sync_fixed import ONE
from model.viterbi_fixed import acs, path_metric_bits, quantize, traceback_block, traceback_sliding

SOFT_BITS, SHIFT = 4, 10  # ADR 0005
DEPTHS = (12, 18, 24, 30, 36, 42, 48, 60, 72, 96)
BLOCKS, N, EDGE = 128, 4096, 64
STOP = N - 128  # last bit compared: inside every depth's sliding output (N - 1 - 96)
JOBS, BATCHES = 8, 3  # per Eb/N0: 8 x 3 x 128 x 3,904 = 12.0 M bits
POINTS = (2.5, 3.0, 4.0)


def job(args: tuple[float, int]) -> dict[str, int]:
    ebn0_db, seed = args
    rng = np.random.default_rng(int(ebn0_db * 100) * 100 + seed)
    sigma = np.sqrt(1 / 10 ** (ebn0_db / 10))
    errors = {"full": 0} | {f"{s}{d}": 0 for s in ("best", "zero") for d in DEPTHS}
    for _ in range(BATCHES):
        data = rng.integers(0, 2, (BLOCKS, N), dtype=np.uint8)
        coded = np.stack([conv_encode(d) for d in data]).astype(np.float64) * 2 - 1
        x = (coded + sigma * rng.standard_normal(coded.shape)) / np.sqrt(1 + sigma * sigma)
        u = quantize(np.round(x * ONE).astype(np.int64), SOFT_BITS, SHIFT)
        decisions, best, _ = acs(u, SOFT_BITS, path_metric_bits(SOFT_BITS))
        want = data[:, EDGE:STOP]
        errors["full"] += int(np.count_nonzero(traceback_block(decisions, best[-1])[:, EDGE:STOP] != want))
        for start, starts in (("best", best), ("zero", np.zeros_like(best))):
            for d in DEPTHS:
                got = traceback_sliding(decisions, starts, d)[:, EDGE:STOP]
                errors[f"{start}{d}"] += int(np.count_nonzero(got != want))
    errors["bits"] = BATCHES * BLOCKS * (STOP - EDGE)
    return errors


def main() -> None:
    with Pool() as pool:
        results = pool.map(job, [(e, s) for e in POINTS for s in range(JOBS)])
    rows = []
    for i, ebn0 in enumerate(POINTS):
        part = results[i * JOBS : (i + 1) * JOBS]
        bits = sum(r["bits"] for r in part)
        configs = [("full", "block", 0)] + [(f"{s}{d}", s, d) for s in ("best", "zero") for d in DEPTHS]
        for key, start, depth in configs:
            err = sum(r[key] for r in part)
            rows.append([ebn0, start, depth, bits, err, err / bits, err < MIN_ERRORS])
            print(rows[-1])
    write_result(
        "traceback_depth",
        ["ebn0_db", "start", "depth", "bits", "errors", "ber", "upper_bound"],
        rows,
        seed="noise seed from Eb/N0 and job index; 4-bit soft, step ONE/4; depth 0 = full-block traceback",
    )


if __name__ == "__main__":
    main()
