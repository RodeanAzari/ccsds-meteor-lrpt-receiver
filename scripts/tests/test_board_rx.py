"""parse_cadu against packets built by hand from docs/protocol.md "CADU"; freq-word against the board-top test;
set_nco_command against docs/protocol.md "Control commands".

Why it matters: the hardware check and the ground station read every CADU through this layout; a status bit or
the body one byte off would pass garbage as decoded, or blame RS for a parsing error. The NCO word the host tool
computes is the one it sends the board: it must be the word the bit-true model and the RTL test use, and the
command must have the exact bytes ctrl_rx accepts (a byte-swapped word tunes the DDC megahertz away).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from scripts.board_rx import N_PAYLOAD, freq_word, parse_cadu, set_nco_command


def packet(flags: int = 0b101, asm: int = 3, rs: tuple[int, ...] = (0, 16, 0x80, 7), seq: int = 9,
           body: bytes = bytes(range(256)) * 4, ptype: int = 2, version: int = 1, n: int = N_PAYLOAD,
           reserved: bytes = b"\0\0") -> bytes:
    hdr = bytes([ptype, version]) + n.to_bytes(2, "big") + seq.to_bytes(4, "big") + (55).to_bytes(8, "big")
    return hdr + bytes([flags, asm, *rs]) + reserved + body


def test_fields_in_protocol_order() -> None:
    c = parse_cadu(packet())
    assert (c.pkt_seq, c.uptime) == (9, 55)
    assert (c.alternate, c.swap, c.flywheel) == (True, False, True)  # flags bit 0, 1, 2
    assert c.asm_errors == 3
    assert c.corrections == (0, 16, -1, 7)  # codeword 2 failed (bit 7)
    assert c.data == bytes(range(256)) * 4 and len(packet()) == 1048


@pytest.mark.parametrize(
    "data, why",
    [
        (packet(ptype=1), "type"),
        (packet(version=2), "version"),
        (packet(n=1031), "n = 1031"),
        (packet()[:-1], "bytes for n"),
        (packet(flags=0b1000), "reserved bits"),
        (packet(asm=33), "out-of-range"),
        (packet(rs=(0x20, 0, 0, 0)), "reserved bits"),
        (packet(rs=(0x81, 0, 0, 0)), "out-of-range"),  # fail with a nonzero count
        (packet(rs=(17, 0, 0, 0)), "out-of-range"),
        (packet(reserved=b"\0\1"), "reserved bytes"),
        (b"\x02\x01", "short"),
    ],
)
def test_malformed_rejected(data: bytes, why: str) -> None:
    with pytest.raises(ValueError, match=why):
        parse_cadu(data)


def test_freq_word_matches_board_top_test(tmp_path: Path) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tb/cocotb"))
    from sync_chain import raw_input  # type: ignore[import-not-found]
    from test_arty_rx_eth_top_full import FRAMES, FREQ_WORD, SAMPLES, SEED  # type: ignore[import-not-found]

    raw, _, _ = raw_input(FRAMES, SEED)
    path = tmp_path / "r.cu8"
    raw[: raw.size // (2 * SAMPLES) * 2 * SAMPLES].tofile(path)
    word, hz = freq_word(path, 150_000.0, seconds=10.0)
    assert word == FREQ_WORD and abs(hz - 151_000) < 100


def test_set_nco_command_bytes() -> None:
    """docs/protocol.md: 0x80000001 then the word, both u32 big-endian, 8 bytes; byte 0 bit 7 marks a command."""
    assert set_nco_command(0x25C0_EE00) == bytes.fromhex("80000001 25c0ee00")
    assert set_nco_command(0) == bytes.fromhex("80000001 00000000")
    assert set_nco_command(0xFFFF_FFFF) == bytes.fromhex("80000001 ffffffff")


@pytest.mark.parametrize("word", [-1, 1 << 32])
def test_set_nco_word_out_of_range(word: int) -> None:
    with pytest.raises(ValueError, match="not a u32"):
        set_nco_command(word)


def test_dump_keeps_every_packet_in_arrival_order(tmp_path: Path) -> None:
    """The dump exists to diagnose broken replays (docs/log.md 2026-11-08: counters near 2^32, a 163-byte
    CADU-typed packet), so it must keep the corrupt packets byte for byte and the good ones by field, in arrival
    order; dropping or reordering them would hide when a counter jumped."""
    import csv
    import struct

    from scripts.board_rx import Replay, dump_replay
    from scripts.board_stats import FIELDS, HDR

    def stats(seq: int, fields: list[int]) -> bytes:
        return HDR.pack(1, 2, len(fields), seq, 1000 + seq) + struct.pack(f">{len(fields)}I", *fields)

    good = stats(3, list(range(len(FIELDS))))
    torn = stats(4, list(range(len(FIELDS))))[:-5]
    odd = bytes([2, 1, 0, 147]) + bytes(159)  # 163 bytes, CADU-typed, wrong length
    rp = Replay([], ["x"], {}, "", stats_history=[(10.0, good), (10.2, torn)], malformed_raw=[(10.1, odd)])
    path = tmp_path / "d" / "r.csv"
    dump_replay(rp, path)
    rows = list(csv.DictReader(path.open()))
    assert [r["kind"] for r in rows] == ["stats", "bad_other", "bad_stats"]
    assert [r["t_s"] for r in rows] == ["0.0000", "0.1000", "0.2000"]
    assert rows[0]["pkt_seq"] == "3" and rows[0]["uptime"] == "1003"
    assert rows[0]["mac_restarts"] == str(FIELDS.index("mac_restarts")) and rows[0]["ctrl_bad"] == "28"
    assert bytes.fromhex(rows[1]["hex"]) == odd and rows[1]["len"] == "163"
    assert bytes.fromhex(rows[2]["hex"]) == torn and "bytes for n" in rows[2]["error"]
