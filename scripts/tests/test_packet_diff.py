"""scripts/packet_diff.py on streams built by model/space_packets.py `mux`, with known damage.

Why it matters: on a real pass, gs-rx's packets and SatDump's will differ around every CADU one side lost (ADR 0015:
SatDump emits a damaged packet there, gs-rx drops it). The comparison must call those differences expected and
still fail on any difference with no lost CADU, length quirk or tail effect behind it. Our side here is
`demux` (the golden model gs-rx equals, gs/tests); SatDump's is its port `satdump_demux`, run by packet_diff itself.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from model.space_packets import ZONE_BYTES, ZONE_START, demux, mux, packet_length, satdump_demux, space_packet
from scripts.packet_diff import InputError, compare, main

BIG = 3 * ZONE_BYTES  # a packet over four zones: losing its second CADU damages it


def stream(seed: int = 1) -> list[bytes]:
    rng = random.Random(seed)
    pkts = [space_packet(rng.randrange(2047), k, rng.randbytes(rng.randint(40, 400))) for k in range(6)]
    big = space_packet(9, 6, rng.randbytes(BIG))
    return mux([*pkts, big, *[space_packet(3, 7 + k, rng.randbytes(rng.randint(40, 400))) for k in range(8)]],
               first_counter=100)


def big_cadus(cadus: list[bytes]) -> list[int]:
    """Indices of the CADUs the BIG packet's bytes lie in (located from the zones, not from the code under test)."""
    zones = b"".join(c[ZONE_START:ZONE_START + ZONE_BYTES] for c in cadus)
    pos = zones.find(space_packet(9, 6, b"x")[:4])
    return list(range(pos // ZONE_BYTES, (pos + 6 + BIG - 1) // ZONE_BYTES + 1))


def ours(cadus: list[bytes]) -> list[bytes]:
    return demux(cadus)[0]


def test_same_cadus_agree() -> None:
    c = stream()
    d = compare(c, ours(c), c)
    assert d.passed and d.unexplained == [] and d.differ == d.only_satdump == 0
    assert d.equal == d.satdump == d.ours == len(satdump_demux(c))


def test_satdump_tail_is_explained() -> None:
    # The last zone's first packet starts at its pointer (0) and fills it: SatDump would push it at the next CADU.
    c = mux([space_packet(1, 0, bytes(ZONE_BYTES - 6)), space_packet(2, 1, bytes(ZONE_BYTES - 6))])
    assert len(c) == 2
    d = compare(c, ours(c), c)
    assert (d.equal, d.only_ours, d.explained["satdump_tail"]) == (1, 1, 1)
    assert d.passed

    # Not when SatDump's last CADU says no packet starts there (pointer 2047; gs-diff fails on those data bytes too).
    sd = [c[0], bytes(c[1][:12]) + bytes([0x07, 0xFF]) + c[1][14:]]
    d = compare(c, ours(c), sd)
    assert not d.passed and d.unexplained[0].startswith("only_ours")


def test_cadu_satdump_lost_explains_both_differences() -> None:
    c = stream()
    lost = big_cadus(c)[1]
    d = compare(c, ours(c), c[:lost] + c[lost + 1:])
    # SatDump's BIG packet continues with the next CADU's bytes: same start, other bytes, damaged on its side.
    assert d.differ == 1 and d.explained["satdump_damaged"] == 1
    assert d.passed, d.unexplained


def test_full_length_packet_across_satdump_gap() -> None:
    # SatDump loses the CADU where BIG ends and BIG2 starts; BIG then completes, full length, in BIG2's next zone
    # (pointer 2047): not short, so only the gap shows the damage. BIG2's start is in the lost CADU.
    rng = random.Random(3)
    c = mux([space_packet(9, 6, rng.randbytes(BIG)), space_packet(4, 0, rng.randbytes(3 * ZONE_BYTES)),
             space_packet(5, 1, rng.randbytes(100))])
    lost = big_cadus(c)[-1]
    sd = c[:lost] + c[lost + 1:]
    assert all(len(p) == packet_length(p[:6]) for p in satdump_demux(sd))  # none short
    d = compare(c, ours(c), sd)
    assert d.differ == d.explained["satdump_damaged"] == 1
    assert d.only_ours == d.explained["missing_in_satdump"] == 1
    assert d.passed, d.unexplained


def test_cadu_we_lost_is_explained() -> None:
    c = stream()
    lost = big_cadus(c)[1]
    mine = c[:lost] + c[lost + 1:]
    d = compare(mine, ours(mine), c)
    assert d.only_satdump == d.explained["missing_in_ours"] >= 1  # gs-rx dropped BIG (dropped_gap)
    assert d.passed, d.unexplained


def test_length_disagreement_is_satdump_short_packet() -> None:
    c = stream()
    first = bytearray(c[0])
    first[ZONE_START + 5] += 1  # first packet's length field one too long: it overruns the next header
    c[0] = bytes(first)
    d = compare(c, ours(c), c)
    assert d.only_satdump == d.explained["satdump_damaged"] == 1  # gs-rx: dropped_length
    assert d.passed, d.unexplained


def test_length_one_short_is_our_drop() -> None:
    # BIG's length field one too small: SatDump emits it complete (declared length) one byte before the next
    # header; gs-rx sees the length disagree with the pointer and drops it (dropped_length).
    c = stream()
    zones = b"".join(x[ZONE_START:ZONE_START + ZONE_BYTES] for x in c)
    at = zones.find(space_packet(9, 6, b"x")[:4]) + 5  # BIG's length field, low byte
    b = bytearray(c[at // ZONE_BYTES])
    b[ZONE_START + at % ZONE_BYTES] -= 1
    c[at // ZONE_BYTES] = bytes(b)
    d = compare(c, ours(c), c)
    assert d.only_satdump == d.explained["our_drop"] == 1
    assert d.passed, d.unexplained


def test_other_virtual_channels_are_left_out() -> None:
    c = stream()
    other = mux([space_packet(1, k, bytes([k]) * 500) for k in range(5)], vc=37)  # 37: 5 if a VCID bit is lost
    mixed = [x for pair in zip(c, other, strict=False) for x in pair] + c[len(other):]
    d = compare(mixed, ours(mixed), mixed)
    assert d.passed and d.equal == len(ours(c))


def test_invalid_pointer_zone_is_skipped_on_both_sides() -> None:
    c = stream()
    skip = big_cadus(c)[1]
    b = bytearray(c[skip])
    b[12], b[13] = ZONE_BYTES >> 8, ZONE_BYTES & 0xFF  # pointer 882: invalid, the zone is skipped
    c[skip] = bytes(b)
    d = compare(c, ours(c), c)
    assert d.only_satdump == d.explained["satdump_damaged"] == 1  # SatDump keeps BIG across it; gs-rx drops it
    assert d.passed, d.unexplained


# Faults on our side with every CADU present on both: each must be unexplained.

def test_packet_we_dropped_without_cause_fails() -> None:
    c = stream()
    p = ours(c)
    d = compare(c, p[:3] + p[4:], c)
    assert not d.passed and len(d.unexplained) == 1 and d.unexplained[0].startswith("only_satdump")


def test_packet_we_cut_short_fails() -> None:
    c = stream()
    p = ours(c)
    p[2] = p[2][:-1]
    d = compare(c, p, c)
    assert not d.passed and d.unexplained[0].startswith("differ")


def test_packet_we_built_across_a_gap_fails() -> None:
    c = stream()
    lost = big_cadus(c)[1]
    mine = c[:lost] + c[lost + 1:]
    d = compare(mine, satdump_demux(mine), c)  # gs-rx behaving like SatDump: BIG emitted across the gap
    assert not d.passed and any(u.startswith("differ") and "apid:9" in u for u in d.unexplained)


def test_our_packet_across_a_gap_fails_even_where_satdump_has_none() -> None:
    # Both lose a CADU in BIG; SatDump also lacks BIG's first CADU, so it has no packet at BIG's start.
    c = stream()
    span = big_cadus(c)
    mine = [x for k, x in enumerate(c) if k != span[1]]
    sd = [x for k, x in enumerate(c) if k not in (span[0], span[1])]
    d = compare(mine, satdump_demux(mine), sd)
    assert not d.passed and any(u.startswith("only_ours") and "apid:9" in u for u in d.unexplained)


def test_packet_not_in_our_cadus_is_an_input_error() -> None:
    c = stream()
    p = ours(c)
    p[1] = p[1][:-1] + bytes([p[1][-1] ^ 1])
    with pytest.raises(InputError, match="ours: packet 1"):
        compare(c, p, c)


def test_nothing_equal_fails() -> None:
    a, b = stream(1), stream(2)
    b = mux([space_packet(1, 0, bytes(100))], first_counter=5000)
    assert not compare(a, ours(a), b).passed


def test_cli_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    c = stream()
    (tmp_path / "c.bin").write_bytes(b"".join(c))
    (tmp_path / "p.bin").write_bytes(b"".join(ours(c)))
    args = ["--cadus", str(tmp_path / "c.bin"), "--packets", str(tmp_path / "p.bin"), "--satdump"]
    assert main([*args, str(tmp_path / "c.bin")]) == 0
    assert "result=PASS" in capsys.readouterr().out
    (tmp_path / "s.bin").write_bytes(b"".join(stream(2)))  # another recording: same counters, other bytes
    assert main([*args, str(tmp_path / "s.bin")]) == 1
    (tmp_path / "p.bin").write_bytes(b"".join(ours(c))[:-1])
    assert main([*args, str(tmp_path / "c.bin")]) == 2
    assert main([*args, str(tmp_path / "missing")]) == 2
