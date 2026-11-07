"""The post-Viterbi model the RTL is checked against: window bits to CADUs and their status word.

Why it matters: the frame's position in its window, the NRZ-M start bit, the byte order of the interleave and the
status packing are all off-by-one territory; each test pins one of them to an independent fact (the CADUs sent, the
error positions injected, the documented bit layout).
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import pytest

from model.cadu_fixed import FRAME_FIRST_BIT, CaduOut, cadus_from_windows
from model.coding import CODED_FRAME_SYMBOLS, Bits, build_cadus, encode_stream
from model.framesync_fixed import POST_SYMBOLS, PRE_SYMBOLS, Window, decode_windows, frame_sync_fixed, windows
from model.sync_fixed import ONE
from model.tests.framesync_stimulus import rotate
from model.viterbi_fixed import quantize


def _decoded(
    frames: int, seed: int, alternate: bool = False, swap: bool = False
) -> tuple[npt.NDArray[np.uint8], list[Window], Bits, list[int]]:
    plain, on_air = build_cadus(frames, seed)
    soft = rotate((2 * encode_stream(on_air).astype(np.int64) - 1) * ONE, alternate, swap)
    u = quantize(np.concatenate([soft, np.zeros(PRE_SYMBOLS + POST_SYMBOLS, dtype=np.int64)]), 4, 10)
    res = frame_sync_fixed(u)
    wins, early = windows(u, res)
    assert early == 1  # the frame at symbol 0 has no run-in
    # Frames whose window would run past the stream are not emitted (windows()).
    starts = [round(f[0] / CODED_FRAME_SYMBOLS) for f in res.frames[early : early + len(wins)]]
    return plain, wins, decode_windows(wins), starts


@pytest.mark.parametrize(("alternate", "swap"), [(False, False), (True, True)])
def test_clean_windows_give_the_cadus_sent(alternate: bool, swap: bool) -> None:
    plain, wins, bits, starts = _decoded(4, 11, alternate, swap)
    out = cadus_from_windows(bits, wins)
    assert len(out) == 3
    for c, k in zip(out, starts, strict=True):
        assert np.array_equal(c.data, plain[k])  # ASM + derandomized body, RS-encoded as sent
        assert (c.alternate, c.swap, c.flywheel) == (alternate, swap, False)
        assert c.asm_errors == 0
        assert c.corrections == [0, 0, 0, 0]


def _flip_byte(row: Bits, byte: int) -> None:
    # Flipping decoded bit 8k (before NRZ-M) flips plain bits 8k and 8k+1: one byte error, in byte k only.
    row[FRAME_FIRST_BIT + 8 * byte] ^= 1


def test_injected_errors_land_in_the_right_codeword_and_are_reported() -> None:
    plain, wins, bits, starts = _decoded(3, 12)
    bits = bits.copy()
    row = bits[0]
    # Codeword b, byte n is CADU byte 4 + 4n + b (docs/signal-spec.md).
    for n in range(5):
        _flip_byte(row, 4 + 4 * n + 1)  # 5 errors in codeword 1
    for n in range(16):
        _flip_byte(row, 4 + 4 * n + 2)  # 16 in codeword 2: the limit
    for n in range(17):
        _flip_byte(row, 4 + 4 * (n + 100) + 3)  # 17 in codeword 3: uncorrectable
    row[FRAME_FIRST_BIT - 1] ^= 1  # NRZ-M's start bit: flips plain bit 0 only
    row[FRAME_FIRST_BIT + 9] ^= 1  # plain bits 9 and 10
    c = cadus_from_windows(bits[:1], wins[:1])[0]
    assert c.corrections == [0, 5, 16, -1]
    assert c.asm_errors == 3
    want = plain[starts[0]]
    body = np.arange(4, 1024)
    in_cw3 = body[(body - 4) % 4 == 3]
    assert np.array_equal(c.data[4:][(body - 4) % 4 != 3], want[4:][(body - 4) % 4 != 3])
    # Codeword 3 comes out as received: exactly the 17 injected bytes differ.
    assert int(np.count_nonzero(c.data[in_cw3] != want[in_cw3])) == 17
    assert not np.array_equal(c.data[:4], want[:4])


def test_status_word_layout() -> None:
    # The layout cadu_fixed documents and the RTL's tuser follows: [2:0] {flywheel, swap, alternate},
    # [8:3] ASM errors, then {fail, count[4:0]} per codeword from bit 9.
    c = CaduOut(np.zeros(1024, dtype=np.uint8), True, False, True, 37 & 0x3F, [3, -1, 16, 0])
    w = c.status_word()
    assert w & 0b111 == 0b101
    assert (w >> 3) & 0x3F == 37
    assert [(w >> (9 + 6 * i)) & 0x3F for i in range(4)] == [3, 0x20, 16, 0]
    assert w >> 33 == 0
