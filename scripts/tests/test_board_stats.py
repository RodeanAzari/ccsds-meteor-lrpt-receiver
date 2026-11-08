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
    assert s.fields["tx_underrun"] == 0x01020314  # field 16
    assert s.fields["mac_restarts"] == 0x01020315  # field 17, the last of arty_ddc_eth_top
    assert s.fields["cadus_sent"] == 0x01020316  # field 18, the first appended by arty_rx_eth_top
    assert s.fields["fs_locked"] == 0x01020317  # field 19
    assert s.fields["len_err"] == 0x0102031C  # field 24
    assert len(FIELDS) == 25 and len(packet(values)) == 116  # docs/protocol.md packet size


def test_ddc_top_packet_has_the_first_18() -> None:
    """arty_ddc_eth_top sends n = 18: those parse by name, nothing is invented for the rest."""
    s = parse_stats(packet(list(range(18))))
    assert list(s.fields) == list(FIELDS[:18]) and s.fields["mac_restarts"] == 17
    assert len(packet(list(range(18)))) == 88


def test_appended_fields_are_ignored() -> None:
    s = parse_stats(packet(list(range(len(FIELDS) + 3))))
    assert list(s.fields) == list(FIELDS)


@pytest.mark.parametrize(
    "data, why",
    [
        (packet([0] * 18, ptype=2), "type"),
        (packet([0] * 18, version=2), "version"),
        (packet([0] * 18, n=19), "n = 19"),
        (packet([0] * 18)[:-1], "bytes for n"),
        (b"\x01\x01", "short"),
    ],
)
def test_malformed_rejected(data: bytes, why: str) -> None:
    with pytest.raises(ValueError, match=why):
        parse_stats(data)
