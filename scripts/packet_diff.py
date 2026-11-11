"""Our space packets (gs-rx's packets.bin) against SatDump's, from the same recording (ADR 0015, buildplan §8.5).

    PYTHONPATH=. python scripts/packet_diff.py --cadus RX/cadus.bin --packets RX/packets.bin --satdump PASS.cadu

SatDump 1.2.2 writes CADUs, not packets, so its packets are `model.space_packets.satdump_demux` (the statement port of
its demultiplexer) over its .cadu. gs-diff checks the CADUs; this checks what gs-rx built from them.

Matching: each packet is located in its side's VCID-5 packet-zone stream (zones in file order, zones with an invalid
first header pointer left out, as both demultiplexers skip them) and keyed by where it starts: (VCDU counter, offset
in the zone). APID and sequence count are not a key: the 14-bit count wraps within a pass.

On a stretch where both sides have every CADU and nothing disagrees, both demultiplexers emit the same packets
(ADR 0015, model/tests/test_space_packets.py). So a packet only one side has, or one whose bytes differ, is
**explained** (expected) when it touches a place where they may not:

- `satdump_damaged`: SatDump's packet crosses a VCDU counter gap in its stream (another CADU's bytes in it) or is
  shorter than its declared length (`demuxer.cpp:103`). (SatDump cuts a packet in progress at the next first header
  pointer, so its damaged packets never swallow the start of another.)
- `missing_in_ours` / `missing_in_satdump`: the packet spans a CADU the other side does not have.
- `our_drop`: SatDump's packet spans a CADU at which the golden model (`Demux`, which gs-rx equals) run on our CADUs
  drops a packet: a gap, a length that disagrees with the first header pointer, or an invalid pointer.
- `satdump_tail`: ours is the first packet at a zone's first header pointer and ends exactly at the zone's end, in
  SatDump's last VCID-5 CADU; SatDump emits such a packet one CADU late, so never at the end (`signal-spec.md`).

Anything else is **unexplained**, and so is any packet of ours that crosses a gap in our own stream (gs-rx must
never emit one). Prints key=value lines. Exit 0: at least one equal packet and nothing unexplained; 1: not so;
2: unreadable input, a packets.bin that does not split into whole packets, or a packet not found in its stream.
"""

from __future__ import annotations

import argparse
import itertools
import sys
from collections import Counter
from dataclasses import astuple, dataclass, field
from pathlib import Path

from model.space_packets import (
    CADU_BYTES,
    COUNTER_MOD,
    HDR,
    NO_HEADER,
    VCID_MSUMR,
    ZONE_BYTES,
    Demux,
    first_header_pointer,
    packet_length,
    satdump_demux,
    vcdu_counter,
    vcid,
    zone,
)

Key = tuple[int, int]  # (VCDU counter, offset in the zone)


class InputError(Exception):
    pass


def split_cadus(blob: bytes, name: str) -> list[bytes]:
    if len(blob) % CADU_BYTES:
        raise InputError(f"{name}: {len(blob)} bytes is not a whole number of {CADU_BYTES}-byte CADUs")
    return [blob[k:k + CADU_BYTES] for k in range(0, len(blob), CADU_BYTES)]


def split_packets(blob: bytes) -> list[bytes]:
    """packets.bin: packets back to back, each header + length field + 1 bytes."""
    out, pos = [], 0
    while pos < len(blob):
        n = packet_length(blob[pos:pos + HDR]) if len(blob) - pos >= HDR else HDR + 1
        if len(blob) - pos < n:
            raise InputError(f"packets: a partial packet at byte {pos}")
        out.append(blob[pos:pos + n])
        pos += n
    return out


@dataclass
class Located:
    data: bytes
    span: list[int]   # VCDU counters of the zones it lies in


@dataclass
class Stream:
    """A side's VCID-5 zones as both demultiplexers read them, and where its packets lie in them."""

    counters: list[int]
    fhps: list[int]
    data: bytes

    @classmethod
    def of(cls, cadus: list[bytes]) -> Stream:
        kept = [c for c in cadus if vcid(c) == VCID_MSUMR
                and not ZONE_BYTES <= first_header_pointer(c) < NO_HEADER]
        return cls([vcdu_counter(c) for c in kept], [first_header_pointer(c) for c in kept],
                   b"".join(zone(c) for c in kept))

    def locate(self, packets: list[bytes], name: str) -> dict[Key, Located]:
        out, cursor = {}, 0
        for k, p in enumerate(packets):
            pos = self.data.find(p, cursor)
            if pos < 0:
                raise InputError(f"{name}: packet {k} is not in its CADUs' zones")
            span = self.counters[pos // ZONE_BYTES:(pos + len(p) - 1) // ZONE_BYTES + 1]
            out[(self.counters[pos // ZONE_BYTES], pos % ZONE_BYTES)] = Located(p, span)
            cursor = pos + max(1, len(p) - 1)  # SatDump's short packet ends on the next header's first byte
        return out


def crosses_gap(span: list[int]) -> bool:
    return any(b != (a + 1) % COUNTER_MOD for a, b in itertools.pairwise(span))


def drop_counters(cadus: list[bytes]) -> set[int]:
    """VCDU counters of the CADUs at which the golden model drops a packet or skips a zone."""
    d, out = Demux(), set()
    for c in cadus:
        before = astuple(d.counts)[4:]  # dropped_gap, dropped_length, bad_pointer, dropped_pointer
        d.work(c)
        if astuple(d.counts)[4:] != before:
            out.add(vcdu_counter(c))
    return out


@dataclass
class PacketDiff:
    ours: int = 0
    satdump: int = 0
    equal: int = 0
    differ: int = 0
    only_ours: int = 0
    only_satdump: int = 0
    explained: Counter[str] = field(default_factory=Counter)
    unexplained: list[str] = field(default_factory=list)  # "kind counter/offset apid:A seq:S"

    @property
    def passed(self) -> bool:
        return self.equal > 0 and not self.unexplained


def describe(kind: str, key: Key, p: bytes) -> str:
    return f"{kind} {key[0]}/{key[1]} apid:{(p[0] & 0x07) << 8 | p[1]} seq:{(p[2] & 0x3F) << 8 | p[3]}"


def compare(ours_cadus: list[bytes], ours_packets: list[bytes], satdump_cadus: list[bytes]) -> PacketDiff:
    mine, ref = Stream.of(ours_cadus), Stream.of(satdump_cadus)
    mine_at = mine.locate(ours_packets, "ours")
    ref_at = ref.locate(satdump_demux(satdump_cadus), "satdump")
    have_mine, have_ref = set(mine.counters), set(ref.counters)
    our_drops = drop_counters(ours_cadus)
    ref_index = {c: k for k, c in enumerate(ref.counters)}

    def ref_damaged(r: Located) -> bool:
        return crosses_gap(r.span) or len(r.data) < packet_length(r.data[:HDR])

    def why_ref(r: Located) -> str | None:
        if ref_damaged(r):
            return "satdump_damaged"
        if not have_mine.issuperset(r.span):
            return "missing_in_ours"
        return "our_drop" if our_drops.intersection(r.span) else None

    def why_mine(m: Located, key: Key) -> str | None:
        if crosses_gap(m.span):
            return None  # gs-rx must never emit across a gap
        if not have_ref.issuperset(m.span):
            return "missing_in_satdump"
        last = len(ref.counters) - 1
        if (ref_index[m.span[-1]] == last and ref.fhps[last] == key[1] and len(m.span) == 1
                and key[1] + len(m.data) == ZONE_BYTES):
            return "satdump_tail"
        return None

    d = PacketDiff(ours=len(mine_at), satdump=len(ref_at))
    for key in [*ref_at, *(k for k in mine_at if k not in ref_at)]:  # SatDump's stream order, then ours only
        m, r = mine_at.get(key), ref_at.get(key)
        if m and r and m.data == r.data:
            d.equal += 1
            continue
        if m and r:
            d.differ += 1
            why = None if crosses_gap(m.span) else why_ref(r) or why_mine(m, key)
            kind, p = "differ", m.data
        elif m:
            d.only_ours += 1
            why, kind, p = why_mine(m, key), "only_ours", m.data
        else:
            assert r is not None
            d.only_satdump += 1
            why, kind, p = why_ref(r), "only_satdump", r.data
        if why:
            d.explained[why] += 1
        else:
            d.unexplained.append(describe(kind, key, p))
    return d


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--cadus", type=Path, required=True, help="gs-rx's cadus.bin")
    ap.add_argument("--packets", type=Path, required=True, help="gs-rx's packets.bin")
    ap.add_argument("--satdump", type=Path, required=True, help="SatDump's .cadu of the same recording")
    ap.add_argument("--list", type=int, default=10, help="unexplained packets to print")
    a = ap.parse_args(argv)
    try:
        d = compare(split_cadus(a.cadus.read_bytes(), "ours"), split_packets(a.packets.read_bytes()),
                    split_cadus(a.satdump.read_bytes(), "satdump"))
    except (OSError, InputError) as e:
        print(f"packet_diff: {e}", file=sys.stderr)
        return 2
    for k in ("ours", "satdump", "equal", "differ", "only_ours", "only_satdump"):
        print(f"{k}={getattr(d, k)}")
    for why in ("satdump_damaged", "missing_in_ours", "missing_in_satdump", "our_drop", "satdump_tail"):
        print(f"explained_{why}={d.explained[why]}")
    print(f"unexplained={len(d.unexplained)}")
    for line in d.unexplained[:a.list]:
        print(f"unexplained_packet={line.replace(' ', ',')}")
    print(f"result={'PASS' if d.passed else 'FAIL'}")
    return 0 if d.passed else 1


if __name__ == "__main__":
    sys.exit(main())
