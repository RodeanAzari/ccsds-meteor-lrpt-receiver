"""parse_cadu against packets built by hand from docs/protocol.md "CADU"; freq-word against the board-top test.

Why it matters: the hardware check and the ground station read every CADU through this layout; a status bit or
the body one byte off would pass garbage as decoded, or blame RS for a parsing error. The NCO word the host tool
prints is the one the board is built with: it must be the word the bit-true model and the RTL test use.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from scripts.board_rx import N_PAYLOAD, freq_word, parse_cadu


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
