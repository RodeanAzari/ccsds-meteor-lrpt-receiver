"""Test vectors for gs-rx's space packet demultiplexer (gs/tests/space_packets_test.cpp), from the golden model.

    PYTHONPATH=. python scripts/gen_gs_vectors.py [OUT_DIR]     (default gs/tests/data/demux)

Per scenario: <name>.cadu (1,024-byte CADUs back to back), <name>.packets (the packets model/space_packets.py `demux`
emits, back to back: each is self-delimiting by its length field), <name>.counts (its DemuxCounts, one
"field value" per line). scripts/tests/test_gen_gs_vectors.py checks the committed files are what this writes.
"""

from __future__ import annotations

import random
import sys
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from model.space_packets import ZONE_BYTES, ZONE_START, demux, mux, space_packet

OUT = Path("gs/tests/data/demux")


def _packets(rng: random.Random, n: int, lo: int = 1, hi: int = 3000) -> list[bytes]:
    return [space_packet(rng.randrange(0, 2047), k % 16384, rng.randbytes(rng.randint(lo, hi))) for k in range(n)]


def _set_pointer(cadu: bytes, fhp: int) -> bytes:
    b = bytearray(cadu)
    b[12], b[13] = fhp >> 8, fhp & 0xFF
    return bytes(b)


def _length_off(delta: int, seed: int) -> list[bytes]:
    rng = random.Random(seed)
    cadus = mux([space_packet(10, 0, rng.randbytes(1500)), *_packets(rng, 6, 100, 400)])
    bad = bytearray(cadus[0])
    bad[ZONE_START + 5] += delta
    return [bytes(bad), *cadus[1:]]


def _scenarios() -> dict[str, Callable[[], list[bytes]]]:
    def clean(seed: int, n: int) -> Callable[[], list[bytes]]:
        def f() -> list[bytes]:
            rng = random.Random(seed)
            return mux(_packets(rng, n), first_counter=rng.randrange(1 << 24))
        return f

    def lost() -> list[bytes]:
        rng = random.Random(2)
        c = mux([*_packets(rng, 3, 50, 300), space_packet(9, 0, rng.randbytes(3 * ZONE_BYTES)),
                 *_packets(rng, 5, 50, 300)])
        return c[:2] + c[3:]

    def bad_pointer() -> list[bytes]:
        rng = random.Random(5)
        c = mux([space_packet(12, 0, rng.randbytes(2 * ZONE_BYTES)), *_packets(rng, 4, 100, 400)])
        return [c[0], _set_pointer(c[1], ZONE_BYTES), *c[2:], *mux(_packets(rng, 3), first_counter=len(c))[:1]]

    def mixed_vcid() -> list[bytes]:
        """VCID 5 interleaved with VCID 63 (fill) and 37 (0b100101: VCID 5 if only 5 of its 6 bits are read)."""
        rng = random.Random(1)
        mine, other, near = mux(_packets(rng, 10)), mux(_packets(rng, 10), vc=63), mux(_packets(rng, 6), vc=37)
        out = [c for pair in zip(mine, other, strict=False) for c in pair] + mine[len(other):] + other[len(mine):]
        return [c for k, c in enumerate(out) for c in ([c, near[k // 3]] if k % 3 == 2 and k // 3 < len(near)
                                                         else [c])]

    def split_headers() -> list[bytes]:
        """Packet headers starting d = 0..7 bytes before a zone's end: each filler packet ends exactly there."""
        pkts, used = [], 0
        for d in range(8):
            target = (used // ZONE_BYTES + 2) * ZONE_BYTES - d
            pkts.append(space_packet(1, d, bytes(target - used - 6)))
            used = target
        pkts.append(space_packet(2, 8, bytes(range(100))))
        return mux(pkts)

    def wrap() -> list[bytes]:
        return mux([space_packet(6, 0, bytes(2000)), *_packets(random.Random(7), 5)], first_counter=(1 << 24) - 2)

    return {"clean_small": clean(10, 5), "clean_large": clean(11, 200), "lost_cadu": lost,
            "length_plus1": lambda: _length_off(+1, 3), "length_minus1": lambda: _length_off(-1, 4),
            "bad_pointer": bad_pointer, "mixed_vcid": mixed_vcid, "split_headers": split_headers, "wrap": wrap}


def generate(out: Path) -> list[str]:
    out.mkdir(parents=True, exist_ok=True)
    names = []
    for name, make in _scenarios().items():
        cadus = make()
        pkts, counts = demux(cadus)
        (out / f"{name}.cadu").write_bytes(b"".join(cadus))
        (out / f"{name}.packets").write_bytes(b"".join(pkts))
        (out / f"{name}.counts").write_text("".join(f"{k} {v}\n" for k, v in asdict(counts).items()))
        names.append(name)
    return names


if __name__ == "__main__":
    print(" ".join(generate(Path(sys.argv[1]) if len(sys.argv) > 1 else OUT)))
