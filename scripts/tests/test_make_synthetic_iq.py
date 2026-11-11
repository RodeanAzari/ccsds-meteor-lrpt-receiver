"""The packet-carrying synthetic recording's CADUs (make_synthetic_iq.py --packets), checked against the CCSDS layout.

Why it matters: this recording is the hardware test of gs-rx's packet path. If its CADUs were not a valid VCID-5
M_PDU stream (a first header pointer off, a counter jump, a packet header miscounted) the board run would measure
the generator, not the receiver. The expected packets come from walking the zone stream by its length fields
(signal-spec.md byte map), not from the generator's own list.
"""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from model.coding import ASM_BYTES, DATA_BYTES, build_cadus, encode_cadus
from model.space_packets import (
    HDR,
    NO_HEADER,
    VCID_MSUMR,
    ZONE_BYTES,
    demux,
    first_header_pointer,
    packet_length,
    vcdu_counter,
    vcid,
    zone,
)
from scripts.make_synthetic_iq import APIDS, packet_cadus

N = 40


def cadus_of(rows: np.ndarray) -> list[bytes]:
    return [ASM_BYTES + r.tobytes() + bytes(1024 - 4 - DATA_BYTES) for r in rows]


@pytest.fixture(scope="module")
def cadus() -> list[bytes]:
    return cadus_of(packet_cadus(N, 7))


def walk(stream: bytes) -> tuple[list[bytes], list[int]]:
    """Complete packets and every packet start, from offset 0 by the length fields."""
    out, starts, pos = [], [], 0
    while pos + HDR <= len(stream):
        starts.append(pos)
        end = pos + packet_length(stream[pos:pos + HDR])
        if end > len(stream):
            break
        out.append(stream[pos:end])
        pos = end
    return out, starts


def test_unbroken_vcid5_stream(cadus: list[bytes]) -> None:
    assert all(vcid(c) == VCID_MSUMR for c in cadus)
    counters = [vcdu_counter(c) for c in cadus]
    assert all((b - a) % (1 << 24) == 1 for a, b in itertools.pairwise(counters))


def test_pointers_and_packets_follow_the_layout(cadus: list[bytes]) -> None:
    stream = b"".join(zone(c) for c in cadus)
    packets, starts = walk(stream)
    for k, c in enumerate(cadus):
        inside = [s - k * ZONE_BYTES for s in starts if k * ZONE_BYTES <= s < (k + 1) * ZONE_BYTES]
        assert first_header_pointer(c) == (inside[0] if inside else NO_HEADER), k
    assert len(stream) - sum(map(len, packets)) > 0  # cut mid-packet, as at the end of a pass
    got, counts = demux(cadus)
    assert got == packets and counts.packets == len(packets) > N // 3
    assert counts.dropped_gap == counts.dropped_length == counts.bad_pointer == 0


def test_apids_and_sequence_counts(cadus: list[bytes]) -> None:
    packets, _ = walk(b"".join(zone(c) for c in cadus))
    seen: dict[int, list[int]] = {}
    for p in packets:
        seen.setdefault((p[0] & 0x07) << 8 | p[1], []).append((p[2] & 0x3F) << 8 | p[3])
        assert p[2] >> 6 == 3  # unsegmented
    assert set(seen) <= set(APIDS) and len(seen) > 1
    assert all(s == list(range(len(s))) for s in seen.values())


def test_encode_cadus_is_systematic_and_matches_build_cadus() -> None:
    plain, on_air = build_cadus(3, 11)
    again, again_air = encode_cadus(plain[:, 4:4 + DATA_BYTES])
    assert np.array_equal(again, plain) and np.array_equal(again_air, on_air)
    with pytest.raises(ValueError):
        encode_cadus(np.zeros((2, DATA_BYTES - 1), dtype=np.uint8))
