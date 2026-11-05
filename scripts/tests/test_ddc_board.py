"""Host side of the board check: a broken UART dump must never be reported as a DDC error.

On 2026-11-04 opening the serial port reset the board, which restarted its dump; the host took the cut-off dump's
header and read on into the next dump, and reported 16,169 "DDC mismatches" on a correct design (docs/log.md).
"""

from __future__ import annotations

import struct
import zlib

import numpy as np
import pytest

from scripts.ddc_board import find_dump, parse_dump


def make_dump(words: np.ndarray) -> bytes:
    body = b"DDC1" + struct.pack("<I", words.shape[0]) + words.astype("<i2").tobytes()
    return body + struct.pack("<I", zlib.crc32(body))


WORDS = np.random.default_rng(0).integers(-32768, 32768, (64, 2))


def test_truncated_dump_followed_by_a_full_one_yields_the_full_one() -> None:
    good = make_dump(WORDS)
    stream = b"\x00\xff" + good[:891 % len(good)] + good  # cut off mid-dump, then restarted
    dump, _ = find_dump(stream, WORDS.shape[0])
    assert dump == good
    assert (parse_dump(dump) == WORDS).all()


def test_a_single_flipped_bit_is_a_link_error_not_data() -> None:
    bad = bytearray(make_dump(WORDS))
    bad[100] ^= 0x04
    with pytest.raises(ValueError, match="CRC"):
        parse_dump(bytes(bad))
    assert find_dump(bytes(bad), WORDS.shape[0])[0] is None


def test_incomplete_stream_waits_for_more_bytes() -> None:
    good = make_dump(WORDS)
    dump, resume = find_dump(good[:-1], WORDS.shape[0])
    assert dump is None and resume == 0  # the header is still a candidate once the rest arrives
