#!/usr/bin/env python3
"""Write a synthetic pass-like recording, plus truth, for an independent check in SatDump.

If SatDump 1.2.2 decodes this file and its CADUs match the truth, our transmit chain and SatDump's
receive chain agree, without anyone having to trust this repo's own receiver.

Run from the repo root: PYTHONPATH=. python scripts/make_synthetic_iq.py
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from model.channel import TxConfig, apply_carrier, awgn, modulate, noise_sigma, to_cu8
from model.coding import build_cadus, encode_stream

OUT = Path("data/synthetic")
FRAMES = 300  # about 34 s of signal
SEED = 2026
EBN0_DB = 8.0
TUNE_OFFSET_HZ = 150_000.0


def main() -> None:
    plain, on_air = build_cadus(FRAMES, SEED)
    tx = TxConfig(timing_offset_sym=0.37, clock_ppm=20.0)
    x = apply_carrier(modulate(encode_stream(on_air), tx), tx.fs, TUNE_OFFSET_HZ + 1000.0, 30.0, 0.7)
    sigma = noise_sigma(EBN0_DB, tx.fs)
    raw = to_cu8(awgn(x, sigma, SEED), full_scale=4 * sigma)

    OUT.mkdir(parents=True, exist_ok=True)
    iq = OUT / f"synthetic_seed{SEED}_1024000SPS.cu8"
    raw.tofile(iq)
    # Same content SatDump writes to its .cadu: derandomized body, ASM in front.
    plain.tofile(OUT / f"synthetic_seed{SEED}_truth.cadu")
    digest = hashlib.sha256(raw.tobytes()).hexdigest()
    print(f"{iq}  {iq.stat().st_size} bytes  sha256 {digest}")
    print(f"frames {FRAMES}, Eb/N0 {EBN0_DB} dB, signal offset +{TUNE_OFFSET_HZ:.0f} Hz + 1 kHz, 30 Hz/s ramp")
    print(f"rms check: {np.std(raw.astype(float)):.1f} LSB")


if __name__ == "__main__":
    main()
