"""Space packet demultiplexing (docs/signal-spec.md "Frame layers above the CADU", ADR 0015).

Why it matters: Phase F's definition of done is space packets matching SatDump bit for bit, so `satdump_demux` (the
port) must be SatDump's behaviour and `demux` (gs-rx's golden model) must equal it wherever SatDump is right: on an
unbroken VCID-5 stream. Where SatDump is wrong (a CADU lost mid-packet; a length that disagrees with the first
header pointer), `demux` must drop the damaged packet, count it, and lose nothing else. Expected values come from
the CCSDS layout in signal-spec.md via `mux` (packets in, CADUs out), not from either demultiplexer.
"""

from __future__ import annotations

import random

import pytest

from model.space_packets import (
    APID_IDLE,
    NO_HEADER,
    ZONE_BYTES,
    ZONE_START,
    DemuxCounts,
    demux,
    first_header_pointer,
    idle_fill,
    mux,
    satdump_demux,
    space_packet,
    vcdu_counter,
)


def packets(rng: random.Random, n: int, lo: int = 1, hi: int = 3000) -> list[bytes]:
    return [space_packet(rng.randrange(0, 2047), k % 16384, rng.randbytes(rng.randint(lo, hi))) for k in range(n)]


def with_fill(pkts: list[bytes]) -> list[bytes]:
    return pkts + idle_fill(sum(len(p) for p in pkts))


def sd(cadus: list[bytes]) -> list[bytes]:
    """satdump_demux with one more VCID-5 CADU (no packet header, next counter) after the stream: SatDump emits a
    packet that starts at a zone's first header pointer and ends exactly at that zone's end only when the next CADU
    arrives (signal-spec.md), and every mux stream ends that way."""
    flush = set_pointer(mux([space_packet(0, 0, b"x")])[0], NO_HEADER)  # VCID 5; SatDump reads no counter
    return satdump_demux([*cadus, flush])


def set_pointer(cadu: bytes, fhp: int) -> bytes:
    b = bytearray(cadu)
    b[12], b[13] = fhp >> 8, fhp & 0xFF
    return bytes(b)


def test_mux_layout_follows_the_spec() -> None:
    """signal-spec.md byte map: VCID 5 in byte 5, counter in bytes 6-8, pointer in bytes 12-13, zone from 14."""
    p = space_packet(70, 1, bytes(range(100)))
    cadus = mux([p], scid=0x9A, first_counter=0x123456)
    assert len(cadus) == 1 and len(cadus[0]) == 1024
    c = cadus[0]
    assert c[:4] == bytes.fromhex("1ACFFC1D")
    assert c[4] >> 6 == 1 and ((c[4] & 0x3F) << 2 | c[5] >> 6) == 0x9A and c[5] & 0x3F == 5
    assert vcdu_counter(c) == 0x123456 and first_header_pointer(c) == 0
    assert c[ZONE_START: ZONE_START + len(p)] == p
    assert int.from_bytes(p[4:6], "big") == 99 and (p[0] & 0x07) << 8 | p[1] == 70  # length - 1, APID


@pytest.mark.parametrize("seed", range(20))
def test_unbroken_stream_both_recover_every_packet(seed: int) -> None:
    """The property everything rests on: what went in comes out, from both, identically."""
    rng = random.Random(seed)
    pkts = packets(rng, rng.randint(1, 60))
    cadus = mux(pkts, first_counter=rng.randrange(1 << 24))
    want = with_fill(pkts)
    got, counts = demux(cadus)
    assert got == want
    assert sd(cadus) == want
    assert counts == DemuxCounts(cadus=len(cadus), packets=len(want))


@pytest.mark.parametrize("header_at", [ZONE_BYTES - 6, ZONE_BYTES - 5, ZONE_BYTES - 1, ZONE_BYTES - 7])
def test_header_split_across_zones(header_at: int) -> None:
    """A packet header that starts 1-6 bytes before a zone's end continues in the next zone (signal-spec.md); at
    exactly 6 bytes before, it fits but SatDump still treats it as split (demuxer.cpp:125)."""
    first = space_packet(1, 0, bytes(header_at - 6))  # ends exactly at header_at
    second = space_packet(2, 1, bytes(range(200)))
    want = with_fill([first, second])
    cadus = mux([first, second])
    assert demux(cadus)[0] == want and sd(cadus) == want


def test_packet_ending_exactly_at_zone_end_and_long_packet_spanning_zones() -> None:
    """Packet boundaries on zone boundaries, and a packet over several zones with NO_HEADER in the middle ones."""
    exact = space_packet(3, 0, bytes(ZONE_BYTES - 6))
    long = space_packet(4, 1, bytes(i % 251 for i in range(5 * ZONE_BYTES)))
    pkts = [exact, long, space_packet(5, 2, b"x")]
    cadus = mux(pkts)
    assert [first_header_pointer(c) for c in cadus[:4]] == [0, 0, NO_HEADER, NO_HEADER]
    want = with_fill(pkts)
    assert demux(cadus)[0] == want and sd(cadus) == want


def test_counter_wraps_without_a_gap() -> None:
    pkts = [space_packet(6, 0, bytes(2000))]
    cadus = mux(pkts, first_counter=(1 << 24) - 2)
    assert [vcdu_counter(c) for c in cadus] == [(1 << 24) - 2, (1 << 24) - 1, 0]
    got, counts = demux(cadus)
    assert got == with_fill(pkts) and counts.gaps == 0


def test_other_virtual_channels_ignored() -> None:
    rng = random.Random(1)
    pkts = packets(rng, 10)
    mine = mux(pkts)
    other = mux(packets(rng, 10), vc=63) + mux(packets(rng, 6), vc=37)  # 37 = 0b100101: VCID 5 in its low 5 bits
    mixed = [c for pair in zip(mine, other, strict=False) for c in pair] + mine[len(other):] + other[len(mine):]
    got, counts = demux(mixed)
    assert got == with_fill(pkts) and sd(mixed) == with_fill(pkts)
    assert counts.other_vcid == len(other) and counts.gaps == 0  # counters are per VCID-5 stream


def test_lost_cadu_mid_packet() -> None:
    """A CADU lost inside a long packet. demux: that packet is dropped and counted, every other packet intact.
    SatDump: emits it anyway, with another CADU's bytes in the middle (signal-spec.md: no counter check)."""
    rng = random.Random(2)
    before, long, after = packets(rng, 3, 50, 300), space_packet(9, 0, rng.randbytes(3 * ZONE_BYTES)), packets(
        rng, 5, 50, 300)
    cadus = mux([*before, long, *after])
    lost = 2  # the long packet starts in zone 0 and covers zones 1-3: zone 2 carries only its bytes
    assert first_header_pointer(cadus[lost]) == NO_HEADER
    damaged = cadus[:lost] + cadus[lost + 1:]
    want = [q for q in with_fill([*before, long, *after]) if q != long]  # the stream's own idle fill
    got, counts = demux(damaged)
    assert got == want
    assert (counts.gaps, counts.dropped_gap, counts.packets) == (1, 1, len(want))
    sdo = sd(damaged)
    assert long not in sdo and len(sdo) == len(got) + 1  # SatDump's version of `long` is wrong, but it is there


def test_length_disagreeing_with_pointer_is_dropped_then_resynced() -> None:
    """A packet whose length field says one byte more than the next header pointer allows: dropped and counted;
    demux resyncs at the pointer and the following packets are intact. SatDump keeps it, one byte longer than the
    data before the header and short of its declared length (demuxer.cpp:103)."""
    rng = random.Random(3)
    a = space_packet(10, 0, rng.randbytes(1500))  # spans zones 0-1
    rest = packets(rng, 6, 100, 400)
    cadus = mux([a, *rest])
    bad = bytearray(cadus[0])
    bad[ZONE_START + 5] += 1  # a's length field + 1 (no carry: 1499 = 0x05DB)
    damaged = [bytes(bad), *cadus[1:]]
    want = with_fill([a, *rest])[1:]
    got, counts = demux(damaged)
    assert got == want and counts.dropped_length == 1
    sdo = sd(damaged)
    assert len(sdo[0]) == len(a) + 1 and sdo[0][6:-1] == a[6:] and sdo[1:] == want


def test_packet_ending_before_the_pointer_is_dropped() -> None:
    """Length field one short of what the pointer implies: the packet would end with a byte left before the next
    header. That disagreement drops it as well."""
    rng = random.Random(4)
    a = space_packet(11, 0, rng.randbytes(1500))
    rest = packets(rng, 4, 100, 400)
    cadus = mux([a, *rest])
    bad = bytearray(cadus[0])
    bad[ZONE_START + 5] -= 1
    got, counts = demux([bytes(bad), *cadus[1:]])
    assert got == with_fill([a, *rest])[1:] and counts.dropped_length == 1


def test_invalid_pointer_skips_the_zone() -> None:
    """A first header pointer from 882 to 2046: SatDump skips the M_PDU and keeps going (demuxer.cpp:73); demux
    also drops the packet in progress, since its continuation bytes were in the skipped zone."""
    rng = random.Random(5)
    pkts = [space_packet(12, 0, rng.randbytes(2 * ZONE_BYTES)), *packets(rng, 4, 100, 400)]
    cadus = mux(pkts)
    for fhp in (ZONE_BYTES, 2046):
        damaged = [cadus[0], set_pointer(cadus[1], fhp), *cadus[2:]]
        got, counts = demux(damaged)
        assert (counts.bad_pointer, counts.dropped_pointer) == (1, 1)
        assert pkts[0] not in got and got == [p for p in with_fill(pkts)[1:] if p in got]
        assert got[-len(with_fill(pkts)[2:]):] == with_fill(pkts)[2:]  # everything starting after zone 1 intact


def test_idle_fill_lengths() -> None:
    assert idle_fill(ZONE_BYTES) == []
    assert len(idle_fill(ZONE_BYTES - 7)[0]) == 7
    assert len(idle_fill(ZONE_BYTES - 6)[0]) == 6 + ZONE_BYTES  # too short for a packet: one more zone
    assert (idle_fill(1)[0][0] & 0x07) << 8 | idle_fill(1)[0][1] == APID_IDLE


def test_space_packet_rejects_empty_and_oversize() -> None:
    with pytest.raises(ValueError):
        space_packet(1, 0, b"")
    with pytest.raises(ValueError):
        space_packet(1, 0, bytes((1 << 16) + 1))
