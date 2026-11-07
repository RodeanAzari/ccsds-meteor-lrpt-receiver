"""parse_stats against packets built by hand from docs/protocol.md (big-endian header, then u32 counters).

Why it matters: the hardware campaign reads its loss counters through this parser; a field off by one would
blame the wrong stage for a lost datagram."""

from __future__ import annotations

import pytest

from scripts.board_stats import FIELDS, parse_stats


def packet(values: list[int], ptype: int = 1, version: int = 1, n: int | None = None) -> bytes:
    n = len(values) if n is None else n
    hdr = bytes([ptype, version]) + n.to_bytes(2, "big") + (7).to_bytes(4, "big") + (123456789).to_bytes(8, "big")
    return hdr + b"".join(v.to_bytes(4, "big") for v in values)


def test_fields_in_protocol_order() -> None:
    values = [0x01020304 + k for k in range(len(FIELDS))]
    s = parse_stats(packet(values))
    assert s.pkt_seq == 7 and s.uptime == 123456789
    assert s.fields["ingest_ok"] == 0x01020304  # field 0
    assert s.fields["ingest_lost"] == 0x01020307  # field 3
    assert s.fields["eth_ovf_lost"] == 0x0102030D  # field 9
    assert s.fields["tx_underrun"] == 0x01020314  # field 16, the last of version 1
    assert len(packet(values)) == 84  # docs/protocol.md packet size


def test_appended_fields_are_ignored() -> None:
    s = parse_stats(packet(list(range(len(FIELDS) + 3))))
    assert list(s.fields) == list(FIELDS)


@pytest.mark.parametrize(
    "data, why",
    [
        (packet([0] * 17, ptype=2), "type"),
        (packet([0] * 17, version=2), "version"),
        (packet([0] * 17, n=18), "n = 18"),
        (packet([0] * 17)[:-1], "bytes for n"),
        (b"\x01\x01", "short"),
    ],
)
def test_malformed_rejected(data: bytes, why: str) -> None:
    with pytest.raises(ValueError, match=why):
        parse_stats(data)
