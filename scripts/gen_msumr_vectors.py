"""Test vectors for gs-image's MSU-MR decoder (gs/tests/msumr_test.cpp), from the golden model (model/msumr.py).

    PYTHONPATH=. python scripts/gen_msumr_vectors.py [OUT_DIR]          (default gs/tests/data/msumr)
    PYTHONPATH=. python scripts/gen_msumr_vectors.py --extract PACKETS  (once: writes OUT/real.packets)

real.packets is a slice of the real pass's packets (gs-rx's packets.bin of the 2026-11-21 board replay,
data/MANIFEST.md): whole scans from a channel-1 segment with MCUN 0.
Every scenario is derived from it, deterministically:

- real: as received.
- wrap: sequence counts shifted so the 14-bit count wraps mid-slice; some packets missing, some repeated.
- corrupt: a seeded share of packets damaged (bytes flipped, data cut short, header fields changed): decode
  failures at every point, cut segments, dropped segments, other quality factors.
- swapped: channel 1 and 4 APIDs swapped, so the lowest-offset channel is not channel 1 (the extent shift).
- span: counts rewritten to force rollovers until segments would stretch a channel past 20,000 ids (dropped).
- late_start: the slice from channel 1's segment 12, counts shifted to give it count 11: its MCU number is higher
  than its count, so its offset must wrap (to 16,383 mod 43 = 0).
- tie: channel 1's packets also sent as channel 5 (APID 68), same counts: two channels share the lowest offset.
- edges: not from the pass: one synthetic scan of channel 1 from the model tests' independent T.81 encoder, with
  what real data rarely holds: coefficient 63 set, dense blocks of the largest magnitudes (pixels clip both ways),
  large DC swings, and quality factors across every branch of the scaling (0, 20/21, 49/50, 100/101, 255).

Per scenario: <name>.packets (packets back to back), <name>.summary (per channel: number, extent first and end id,
segments placed) and, unless the images are over MAX_IMAGE_ROWS rows in all (span's are 9,624 rows a channel),
<name>.image (for each of the 6 channels: rows as a little-endian u32, then rows x 1568 pixels).
scripts/tests/test_gen_msumr_vectors.py checks the committed files are what this writes.
"""

from __future__ import annotations

import argparse
import random
import struct
from collections.abc import Callable
from pathlib import Path

import numpy as np

from model.msumr import MCUS, Reader
from model.tests.test_msumr import encode_segment, packet
from scripts.packet_diff import split_packets

OUT = Path("gs/tests/data/msumr")
SCANS = 5
MAX_IMAGE_ROWS = 1000
PACKETS_PER_SCAN = 43


def _apid(p: bytes) -> int:
    return (p[0] & 0x07) << 8 | p[1]


def _seq(p: bytes) -> int:
    return (p[2] & 0x3F) << 8 | p[3]


def _with(p: bytes, *, apid: int | None = None, seq: int | None = None) -> bytes:
    b = bytearray(p)
    if apid is not None:
        b[0], b[1] = (b[0] & 0xF8) | (apid >> 8), apid & 0xFF
    if seq is not None:
        b[2], b[3] = (b[2] & 0xC0) | (seq >> 8), seq & 0xFF
    return bytes(b)


def _with_len(b: bytearray) -> bytes:
    n = len(b) - 7
    b[4], b[5] = n >> 8, n & 0xFF
    return bytes(b)


def extract(packets: Path) -> bytes:
    pkts = split_packets(packets.read_bytes())
    start = next(k for k, p in enumerate(pkts) if k > 1000 and _apid(p) == 64 and len(p) > 14 and p[14] == 0)
    seq0 = _seq(pkts[start])
    out = [p for p in pkts[start:start + SCANS * PACKETS_PER_SCAN + 50]
           if (_seq(p) - seq0) % 16384 < SCANS * PACKETS_PER_SCAN]
    return b"".join(out)


def _scenarios(real: list[bytes]) -> dict[str, Callable[[], list[bytes]]]:
    def wrap() -> list[bytes]:
        rng = random.Random(21)
        shift = (16384 - 2 * PACKETS_PER_SCAN - 7 - _seq(real[0])) % 16384
        out = []
        for p in real:
            q = _with(p, seq=(_seq(p) + shift) % 16384)
            r = rng.random()
            if r < 0.05:
                continue
            out.append(q)
            if r > 0.97:
                out.append(q)
        return out

    def corrupt() -> list[bytes]:
        rng = random.Random(22)
        out = []
        for p in real:
            b = bytearray(p)
            r = rng.random()
            if r < 0.15 and len(b) > 21:  # flip bytes in the entropy-coded data
                for _ in range(rng.randint(1, 3)):
                    b[rng.randrange(20, len(b))] ^= 1 << rng.randrange(8)
            elif r < 0.25 and len(b) > 22:  # cut short
                b = b[:rng.randrange(20, len(b))]
            elif r < 0.30:
                b[19] = rng.randrange(256)  # quality factor
            elif r < 0.33:
                b[14] = rng.randrange(256)  # MCUN
            elif r < 0.36:
                b[rng.choice((15, 16, 17, 18))] ^= 1 << rng.randrange(8)  # header bytes that must hold values
            elif r < 0.38:
                b = b[:rng.randrange(7, 21)]  # too short to hold a segment
            out.append(_with_len(b))
        return out

    def late_start() -> list[bytes]:
        k = next(k for k, p in enumerate(real) if _apid(p) == 64 and p[14] == 12 * MCUS)
        shift = (11 - _seq(real[k])) % 16384
        return [_with(p, seq=(_seq(p) + shift) % 16384) for p in real[k:]]

    def tie() -> list[bytes]:
        out = []
        for p in real:
            out.append(p)
            if _apid(p) == 64:
                out.append(_with(p, apid=68))
        return out

    def swapped() -> list[bytes]:
        swap = {64: 67, 67: 64}
        return [_with(p, apid=swap.get(_apid(p), _apid(p))) for p in real]

    def span() -> list[bytes]:
        # last_seq > 13926 then seq < 2458 adds a rollover; four of them put ids over 20,000 apart.
        out = []
        for k, p in enumerate(real[:60]):
            out.append(_with(p, seq=14000 + k if k % 2 == 0 else 100 + k))
        return out

    def edges() -> list[bytes]:
        rng = np.random.default_rng(23)
        qfs = [0, 1, 20, 21, 36, 48, 49, 50, 51, 80, 100, 101, 200, 255]
        out = []
        for j, qf in enumerate(qfs):
            blocks = []
            for m in range(MCUS):
                dc = 1023 if (j + m) % 2 else -1023  # DC differences of 2046, the largest category 11 holds
                dense = (j + m) % 3 == 0
                ac = rng.integers(-1023, 1024, size=63) if dense else \
                    np.where(rng.random(63) < 0.1, rng.integers(-40, 41, size=63), 0)
                zz = [dc, *(int(v) for v in ac)]
                if m % 2 == 0:
                    zz[63] = int(rng.integers(1, 200))  # coded, but never set (signal-spec.md)
                blocks.append(zz)
            out.append(packet(64, j, encode_segment(blocks, qf=qf, mcun=MCUS * j)))
        return out

    return {"real": lambda: real, "edges": edges, "wrap": wrap, "late_start": late_start, "tie": tie,
            "corrupt": corrupt, "swapped": swapped, "span": span}


def generate(out: Path) -> list[str]:
    real = split_packets((OUT / "real.packets").read_bytes())
    out.mkdir(parents=True, exist_ok=True)
    names = []
    for name, make in _scenarios(real).items():
        pkts = make()
        r = Reader()
        for p in pkts:
            r.add(p)
        summary, image, rows = "", b"", 0
        for ch in range(6):
            first, end = r.extent(ch)
            summary += f"{ch + 1} {first} {end} {len(r.ch[ch].segments)}\n"
            img = r.image(ch)
            rows += img.shape[0]
            image += struct.pack("<I", img.shape[0]) + img.tobytes()
        if name != "real":
            (out / f"{name}.packets").write_bytes(b"".join(pkts))
        (out / f"{name}.summary").write_text(summary)
        if rows <= MAX_IMAGE_ROWS:
            (out / f"{name}.image").write_bytes(image)
        names.append(name)
    return names


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", nargs="?", type=Path, default=OUT)
    ap.add_argument("--extract", type=Path, help="gs-rx packets.bin: write OUT/real.packets from it")
    a = ap.parse_args()
    if a.extract:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "real.packets").write_bytes(extract(a.extract))
    print(" ".join(generate(a.out)))


if __name__ == "__main__":
    main()
