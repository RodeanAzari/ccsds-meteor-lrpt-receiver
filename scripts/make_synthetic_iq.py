#!/usr/bin/env python3
"""Write a synthetic pass-like recording, plus truth, for an independent check in SatDump.

If SatDump 1.2.2 decodes this file and its CADUs match the truth, our transmit chain and SatDump's
receive chain agree, without anyone having to trust this repo's own receiver.

Run from the repo root: PYTHONPATH=. python scripts/make_synthetic_iq.py [--packets]

Default: random CADU data (seed 2026), the recording every board result so far uses. With --packets (seed 2027):
every CADU is a VCID-5 M_PDU carrying space packets on the MSU-MR APIDs (model.space_packets.mux), so the ground
station's packet path has something to recover; the truth packets (the golden model's demux of the truth CADUs) go
next to the truth CADUs.
"""

from __future__ import annotations

import hashlib
import random
import sys
from pathlib import Path

import numpy as np
import numpy.typing as npt

from model.channel import TxConfig, apply_carrier, awgn, modulate, noise_sigma, to_cu8
from model.coding import DATA_BYTES, build_cadus, encode_cadus, encode_stream
from model.space_packets import ZONE_BYTES, demux, mux, space_packet

OUT = Path("data/synthetic")
FRAMES = 300  # about 34 s of signal
SEED = 2026
PACKETS_SEED = 2027
APIDS = range(64, 71)  # signal-spec.md: MSU-MR image APIDs and APID 70 (telemetry)
MAX_PACKET_DATA = 2000  # bytes; spans up to three zones
EBN0_DB = 8.0
TUNE_OFFSET_HZ = 150_000.0


def packet_cadus(n_frames: int, seed: int) -> npt.NDArray[np.uint8]:
    """CADU data bytes 4..895 of `n_frames` VCID-5 CADUs carrying random packets, a sequence count per APID. The
    stream is cut after `n_frames` zones, so the last packet is incomplete, as at the end of a pass."""
    rng = random.Random(seed)
    seq = dict.fromkeys(APIDS, 0)
    packets, used = [], 0
    while used < n_frames * ZONE_BYTES:
        apid = rng.choice(APIDS)
        p = space_packet(apid, seq[apid], rng.randbytes(rng.randint(1, MAX_PACKET_DATA)))
        seq[apid] = (seq[apid] + 1) % (1 << 14)
        packets.append(p)
        used += len(p)
    cadus = mux(packets, first_counter=rng.randrange(1 << 24))[:n_frames]
    return np.stack([np.frombuffer(c[4:4 + DATA_BYTES], dtype=np.uint8) for c in cadus])


def main(argv: list[str]) -> int:
    if argv not in ([], ["--packets"]):
        print(__doc__, file=sys.stderr)
        return 2
    with_packets = argv == ["--packets"]
    seed = PACKETS_SEED if with_packets else SEED
    name = f"synthetic_packets_seed{seed}" if with_packets else f"synthetic_seed{seed}"
    plain, on_air = encode_cadus(packet_cadus(FRAMES, seed)) if with_packets else build_cadus(FRAMES, seed)
    tx = TxConfig(timing_offset_sym=0.37, clock_ppm=20.0)
    x = apply_carrier(modulate(encode_stream(on_air), tx), tx.fs, TUNE_OFFSET_HZ + 1000.0, 30.0, 0.7)
    sigma = noise_sigma(EBN0_DB, tx.fs)
    raw = to_cu8(awgn(x, sigma, seed), full_scale=4 * sigma)

    OUT.mkdir(parents=True, exist_ok=True)
    iq = OUT / f"{name}_1024000SPS.cu8"
    raw.tofile(iq)
    # Same content SatDump writes to its .cadu: derandomized body, ASM in front.
    plain.tofile(OUT / f"{name}_truth.cadu")
    if with_packets:
        packets, counts = demux(bytes(c) for c in plain)
        (OUT / f"{name}_truth.packets").write_bytes(b"".join(packets))
        print(f"truth packets {counts.packets} (dropped {counts.dropped_gap + counts.dropped_length})")
    digest = hashlib.sha256(raw.tobytes()).hexdigest()
    print(f"{iq}  {iq.stat().st_size} bytes  sha256 {digest}")
    print(f"frames {FRAMES}, Eb/N0 {EBN0_DB} dB, signal offset +{TUNE_OFFSET_HZ:.0f} Hz + 1 kHz, 30 Hz/s ramp")
    print(f"rms check: {np.std(raw.astype(float)):.1f} LSB")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
