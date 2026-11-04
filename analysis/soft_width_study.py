"""Soft-decision width: 3-bit vs 4-bit quantization against unquantized soft Viterbi (ADR 0005).

Step 1 sweeps the quantizer step for each width at 3 dB and keeps the best. Step 2 measures BER curves at that step.
Channel: coded +-1 plus AWGN, power-normalized as the AGC does (chain soft rms is 1.04-1.06 ONE, this model 1.0).
Writes data/results/soft_width_step.csv and data/results/soft_width_ber.csv. Run: python -m analysis.soft_width_study
"""

from __future__ import annotations

from itertools import pairwise
from multiprocessing import Pool

import numpy as np

from analysis.ber import MIN_ERRORS
from analysis.common import write_result
from model.coding import conv_encode, viterbi_decode
from model.sync_fixed import ONE
from model.viterbi_fixed import path_metric_bits, quantize, viterbi_fixed

BLOCKS, N, EDGE = 128, 4096, 64
MAX_BITS = 60_000_000
SWEEP_DB = 3.0
WIDTHS = (3, 4)
FLOAT = 0  # width 0 = unquantized soft into the float decoder


def case(args: tuple[int, int, float]) -> list[object]:
    """(width, shift, Eb/N0) -> [width, shift, Eb/N0, bits, errors, ber, upper_bound]. BER before NRZ-M."""
    width, shift, ebn0_db = args
    rng = np.random.default_rng(int(ebn0_db * 100) + 7919)  # same noise for every width at a given Eb/N0
    sigma = np.sqrt(1 / 10 ** (ebn0_db / 10))  # Es = Eb/2 at r = 1/2, sigma^2 = N0/2, amplitude 1
    errors, bits = 0, 0
    while errors < MIN_ERRORS and bits < MAX_BITS:
        data = rng.integers(0, 2, (BLOCKS, N), dtype=np.uint8)
        coded = np.stack([conv_encode(d) for d in data]).astype(np.float64) * 2 - 1
        x = (coded + sigma * rng.standard_normal(coded.shape)) / np.sqrt(1 + sigma * sigma)
        if width == FLOAT:
            decoded = viterbi_decode(x)
        else:
            u = quantize(np.round(x * ONE).astype(np.int64), width, shift)
            decoded = viterbi_fixed(u, width, path_metric_bits(width))[0]
        errors += int(np.count_nonzero(decoded[:, EDGE:-EDGE] != data[:, EDGE:-EDGE]))
        bits += BLOCKS * (N - 2 * EDGE)
    return [width, shift, ebn0_db, bits, errors, errors / bits, errors < MIN_ERRORS]


def loss_at(rows: list[list[object]], width: int, target: float) -> float | None:
    """Eb/N0 at which a curve crosses `target` BER, log-linear between measured points (not upper bounds)."""
    pts = sorted((float(r[2]), float(r[5])) for r in rows if r[0] == width and not r[6] and float(r[5]) > 0)  # type: ignore[arg-type]
    for (e0, b0), (e1, b1) in pairwise(pts):
        if b0 >= target > b1:
            return e0 + (e1 - e0) * (np.log10(b0) - np.log10(target)) / (np.log10(b0) - np.log10(b1))
    return None


def main() -> None:
    with Pool() as pool:
        sweep = pool.map(case, [(w, s, SWEEP_DB) for w in WIDTHS for s in range(7, 13)])
        write_result(
            "soft_width_step",
            ["soft_bits", "shift", "ebn0_db", "bits", "errors", "ber", "upper_bound"],
            sweep,
            seed=f"noise seed from Eb/N0; step = 2^shift / {ONE} of rail rms",
        )
        best = {w: int(min((r for r in sweep if r[0] == w), key=lambda r: float(r[5]))[1]) for w in WIDTHS}  # type: ignore[arg-type]
        print("best shifts", best)
        points = [e / 2 for e in range(4, 10)]
        jobs = [(FLOAT, 0, e) for e in points] + [(w, best[w], e) for w in WIDTHS for e in points]
        curves = pool.map(case, jobs)
    for w in (FLOAT, *WIDTHS):
        at = loss_at(curves, w, 1e-5)
        print(w, "Eb/N0 at 1e-5:", None if at is None else round(at, 2))
    write_result(
        "soft_width_ber",
        ["soft_bits", "shift", "ebn0_db", "bits", "errors", "ber", "upper_bound"],
        curves,
        seed="noise seed from Eb/N0, identical across widths; soft_bits 0 = unquantized float",
    )


if __name__ == "__main__":
    main()
