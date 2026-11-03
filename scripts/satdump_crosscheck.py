#!/usr/bin/env python3
"""Decode synthetic recordings with SatDump and compare its CADUs with truth (data/results/satdump_crosscheck.csv).

Each case is the make_synthetic_iq.py recording with a different carrier offset and ramp, so the leading frames
SatDump misses can be read as its acquisition time rather than a fault in our signal.

Run from the repo root: PYTHONPATH=. python scripts/satdump_crosscheck.py
"""

from __future__ import annotations

import csv
import subprocess
import tempfile
from pathlib import Path

from model.channel import TxConfig, apply_carrier, awgn, modulate, noise_sigma, to_cu8
from model.coding import build_cadus, encode_stream

FRAMES = 300  # same as make_synthetic_iq.py
SEED = 2026
EBN0_DB = 8.0
TUNE_OFFSET_HZ = 150_000.0
FRAME = 1024
DATA = slice(4, 4 + 892)  # signal-spec.md: compare the 892 data bytes only
CASES = [(1000.0, 30.0), (0.0, 0.0), (1000.0, 0.0)]  # (carrier offset Hz, ramp Hz/s); the first is make_synthetic_iq
OUT = Path("data/results/satdump_crosscheck.csv")


def decode(iq: Path, out: Path) -> tuple[bytes, int]:
    cmd = [
        "satdump",
        "meteor_m2-x_lrpt",
        "baseband",
        str(iq),
        str(out),
        "--samplerate",
        "1024000",
        "--baseband_format",
        "cu8",
        "--freq_shift",
        str(-TUNE_OFFSET_HZ),
        "--dc_block",
    ]
    rc = subprocess.run(cmd, capture_output=True).returncode
    return (out / "meteor_m2-x_lrpt.cadu").read_bytes(), rc


def main() -> None:
    plain, on_air = build_cadus(FRAMES, SEED)
    truth = {frame[DATA].tobytes(): n for n, frame in enumerate(plain)}
    tx = TxConfig(timing_offset_sym=0.37, clock_ppm=20.0)
    baseband = modulate(encode_stream(on_air), tx)
    sigma = noise_sigma(EBN0_DB, tx.fs)
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        for offset, ramp in CASES:
            iq = Path(tmp) / "case.cu8"
            x = apply_carrier(baseband, tx.fs, TUNE_OFFSET_HZ + offset, ramp, 0.7)
            to_cu8(awgn(x, sigma, SEED), full_scale=4 * sigma).tofile(iq)
            got, rc = decode(iq, Path(tmp) / f"out_{offset:.0f}_{ramp:.0f}")
            idx = [truth.get(got[i : i + FRAME][DATA]) for i in range(0, len(got), FRAME)]
            found = [i for i in idx if i is not None]
            rows.append(
                {
                    "offset_hz": offset,
                    "ramp_hz_s": ramp,
                    "frames_sent": FRAMES,
                    "frames_decoded": len(idx),
                    "frames_matching": len(found),
                    "first_frame": min(found, default=""),
                    "last_frame": max(found, default=""),
                    "satdump_exit": rc,
                }
            )
            print(rows[-1])
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
