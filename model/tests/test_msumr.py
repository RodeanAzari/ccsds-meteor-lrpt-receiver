"""model.msumr: MSU-MR segments -> pixels, and segment placement, as SatDump does it (signal-spec.md "MSU-MR image
packets").

Why it matters: the image step is judged pixel for pixel against SatDump. The Huffman codes and zigzag order come
from T.81, so they are checked against T.81's own values; the entropy decoder against an independent T.81 encoder
written here; the IDCT against a floating-point DCT; and SatDump's quirks (coefficient 63 never set, a segment cut
short keeps its decoded MCUs, the low nibble of byte 10 checked twice, the shared image extent) each by a case where
they change the result. On the real pass the model gives SatDump's images exactly (analysis/msumr_study.py,
msumr_model.csv); these tests guard the parts on their own and run without the recording.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy.fft import idctn

from model.msumr import (
    AC_BITS,
    AC_VALS,
    DC_BITS,
    DC_VALS,
    K1,
    MCUS,
    WIDTH,
    ZIGZAG,
    Reader,
    decode_coefficients,
    huffman_codes,
    idct,
    quant_table,
    segment_pixels,
)

DC_CODE = {v: k for k, v in huffman_codes(DC_BITS, DC_VALS).items()}
AC_CODE = {v: k for k, v in huffman_codes(AC_BITS, AC_VALS).items()}


def code_str(table: dict[int, tuple[int, int]], sym: int) -> str:
    length, code = table[sym]
    return format(code, f"0{length}b")


def magnitude(v: int) -> tuple[int, str]:
    """T.81 F.1.2.1: size category and its magnitude bits."""
    s = abs(v).bit_length()
    return s, (format(v if v > 0 else v + (1 << s) - 1, f"0{s}b") if s else "")


def encode_block(zz: list[int], prev_dc: int) -> str:
    """One block, coefficients in zigzag order, T.81 baseline Huffman coding (F.1.2)."""
    s, m = magnitude(zz[0] - prev_dc)
    out = code_str(DC_CODE, s) + m
    run = 0
    for v in zz[1:]:
        if v == 0:
            run += 1
            continue
        while run >= 16:
            out += code_str(AC_CODE, 0xF0)
            run -= 16
        s, m = magnitude(v)
        out += code_str(AC_CODE, run << 4 | s) + m
        run = 0
    if zz[63] == 0:
        out += code_str(AC_CODE, 0x00)
    return out


def encode_segment(blocks: list[list[int]], qf: int = 80, mcun: int = 0, header: bytes | None = None) -> bytes:
    bits, dc = "", 0
    for zz in blocks:
        bits += encode_block(zz, dc)
        dc = zz[0]
    bits += "1" * (-len(bits) % 8)
    head = header if header is not None else bytes(8) + bytes([mcun, 0, 0, 0xFF, 0xF0, qf])
    return head + int(bits, 2).to_bytes(len(bits) // 8, "big")


def random_blocks(rng: np.random.Generator, n: int = MCUS) -> list[list[int]]:
    """Sparse blocks like real ones: a DC, a few low-frequency ACs, long zero runs (ZRL), last coefficient 0."""
    out = []
    for _ in range(n):
        zz = [int(rng.integers(-60, 60))] + [0] * 63
        for k in rng.choice(np.arange(1, 63), size=int(rng.integers(0, 12)), replace=False):
            zz[int(k)] = int(rng.integers(-40, 41))
        out.append(zz)
    return out


def natural(zz: list[int]) -> np.ndarray:
    nat = np.zeros(64, dtype=np.int64)
    nat[ZIGZAG] = zz
    return nat


def test_huffman_codes_are_t81_tables_k3_k5() -> None:
    assert sum(DC_BITS) == 12 and sum(AC_BITS) == len(AC_VALS) == 162
    assert code_str(DC_CODE, 0) == "00" and code_str(DC_CODE, 1) == "010" and code_str(DC_CODE, 11) == "111111110"
    assert code_str(AC_CODE, 0x00) == "1010"  # EOB
    assert code_str(AC_CODE, 0xF0) == "11111111001"  # ZRL
    assert code_str(AC_CODE, 0x01) == "00" and code_str(AC_CODE, 0x02) == "01" and code_str(AC_CODE, 0x11) == "1100"
    assert code_str(AC_CODE, 0xFA) == "1111111111111110"


def test_zigzag_is_t81_figure_a6() -> None:
    assert ZIGZAG[:10].tolist() == [0, 1, 8, 16, 9, 2, 3, 10, 17, 24]
    assert ZIGZAG[-4:].tolist() == [47, 55, 62, 63]
    assert sorted(ZIGZAG.tolist()) == list(range(64))


def test_quality_factor_scaling() -> None:
    assert quant_table(50).tolist() == K1.astype(int).tolist()  # f = 100
    assert quant_table(25).tolist() == (2 * K1).astype(int).tolist()  # 20 < QF < 50: f = 5000 / QF = 200
    assert quant_table(20)[0] == int(16 * 1.6 + 0.5)  # QF = 20 is not in (20, 50): f = 200 - 40 = 160
    assert (quant_table(100) == 1).all()  # f = 0: every entry floored at 1
    assert quant_table(80).tolist() == [int(k * 0.4 + 0.5) for k in K1.tolist()]
    # 32-bit float, as SatDump computes it: QF 36 gives f = 5000/36 and K1[44] = 81 lands just below 112.5 in float32
    # (112) and just above in float64 (113). Found by searching QF 0-255; QF 48 entry 14 is the only other case.
    assert quant_table(36)[44] == 112 and quant_table(48)[14] == 62


def test_idct_is_a_dct_to_within_one() -> None:
    rng = np.random.default_rng(3)
    coef = np.zeros((500, 64), dtype=np.int64)
    coef[:, :10] = rng.integers(-400, 400, size=(500, 10))
    coef[:, 20] = rng.integers(-100, 100, size=500)
    want = idctn(coef.reshape(-1, 8, 8).astype(float), axes=(1, 2), norm="ortho").reshape(-1, 64)
    assert np.abs(idct(coef) - want).max() <= 1
    dc = np.arange(-1000, 1001)
    only_dc = np.zeros((dc.size, 64), dtype=np.int64)
    only_dc[:, 0] = dc
    assert (idct(only_dc) == np.floor(dc / 8 + 0.5)[:, None]).all()  # the row shortcut, then the columns


def test_segment_round_trip_from_an_independent_encoder() -> None:
    rng = np.random.default_rng(5)
    blocks = random_blocks(rng)
    blocks[3][1:] = [0] * 30 + [7] + [0] * 32  # a run of 30 zeros: one ZRL
    data = encode_segment(blocks, qf=80, mcun=42)
    coef, done = decode_coefficients(data[14:])
    assert done == MCUS
    assert (coef == np.array([natural(b) for b in blocks])).all()
    seg = segment_pixels(data)
    assert seg is not None and seg.mcun == 42 and seg.pixels.shape == (8, 112)
    deq = np.array([natural(b) for b in blocks]) * quant_table(80)
    want = np.clip(idctn(deq.reshape(-1, 8, 8).astype(float), axes=(1, 2), norm="ortho") + 128, 0, 255)
    got = seg.pixels.reshape(8, MCUS, 8).transpose(1, 0, 2)  # MCU m is columns 8m..8m+7
    assert np.abs(got.astype(int) - want).max() <= 1


def test_coefficient_63_is_never_set_and_the_next_block_still_decodes() -> None:
    blocks = [[10] + [0] * 63 for _ in range(MCUS)]
    blocks[0][63] = 5  # coded as the block's last symbol, no EOB after it
    blocks[0][62] = -3
    coef, done = decode_coefficients(encode_segment(blocks)[14:])
    assert done == MCUS
    assert coef[0, 63] == 0 and coef[0, ZIGZAG[62]] == -3  # natural 63 is zigzag 63
    assert (coef[1:, 0] == 10).all()


def test_a_cut_segment_keeps_the_mcus_before_the_cut() -> None:
    rng = np.random.default_rng(9)
    blocks = random_blocks(rng)
    full = encode_segment(blocks)
    five = len(encode_segment(blocks[:5])) - 14  # bytes holding the first five MCUs (padding included)
    seg = segment_pixels(full[: 14 + five])
    assert seg is not None
    whole = segment_pixels(full)
    assert whole is not None
    # MCUs before the cut as in the whole segment; from the cut on, 0. The padding 1s may decode as part of MCU 5.
    assert (seg.pixels[:, : 5 * 8] == whole.pixels[:, : 5 * 8]).all()
    assert (seg.pixels[:, 6 * 8:] == 0).all()
    assert segment_pixels(full[:15]) is None  # the first MCU itself is cut: the segment is invalid


@pytest.mark.parametrize(("byte", "value", "valid"), [(9, 1, False), (10, 0x01, False), (10, 0x10, True),
                                                      (11, 0xFE, False), (12, 0xF1, False)])
def test_header_fields_that_must_be_zero_or_fixed(byte: int, value: int, valid: bool) -> None:
    data = bytearray(encode_segment(random_blocks(np.random.default_rng(1))))
    data[byte] = value
    assert (segment_pixels(bytes(data)) is not None) == valid  # byte 10: only the low nibble is checked
    assert segment_pixels(bytes(data[:14])) is None


QF_DC = 50  # q[0] = 16: a DC-only block of value d gives pixels 128 + 2d


def flat_segment(value: int, mcun: int) -> bytes:
    return encode_segment([[(value - 128) // 2] + [0] * 63 for _ in range(MCUS)], qf=QF_DC, mcun=mcun)


def packet(apid: int, seq: int, data: bytes) -> bytes:
    return bytes([apid >> 8 & 0x07, apid & 0xFF, 0xC0 | seq >> 8 & 0x3F, seq & 0xFF]) + \
        (len(data) - 1).to_bytes(2, "big") + data


def stream(scans: int, seq0: int, skip: set[tuple[int, int, int]] = frozenset()) -> list[bytes]:  # type: ignore[assignment]
    """The 43-packet loop: 14 segments each of APIDs 64, 65, 68 (channels 1, 2, 5), then telemetry (APID 70).
    Segment (scan s, j) of channel c has the flat value 20 + 28 * (s % 7) + 2 * j + 2 * c (even: a DC-only block
    at QF 50 gives 128 + 2d), unique within a channel, so its place can be read back."""
    out, seq = [], seq0
    for s in range(scans):
        for c, apid in enumerate((64, 65, 68)):
            for j in range(MCUS):
                if (c, s, j) not in skip:
                    out.append(packet(apid, seq % 16384, flat_segment(20 + 28 * (s % 7) + 2 * j + 2 * c, 14 * j)))
                seq += 1
        out.append(packet(70, seq % 16384, bytes(20)))
        seq += 1
    return out


def expected(scans: int, c: int) -> np.ndarray:
    img = np.zeros((scans * 8, WIDTH), dtype=np.uint8)
    for s in range(scans):
        for j in range(MCUS):
            img[8 * s: 8 * s + 8, 112 * j: 112 * j + 112] = 20 + 28 * (s % 7) + 2 * j + 2 * c
    return img


@pytest.mark.parametrize("seq0", [430, 16384 - 43 * 3 - 5])  # the second wraps the 14-bit count mid-stream
def test_segments_are_placed_by_sequence_count(seq0: int) -> None:
    r = Reader()
    for p in stream(6, seq0):
        r.add(p)
    for c, ch in enumerate((0, 1, 4)):
        assert (r.image(ch) == expected(6, c)).all()
    assert all(r.image(ch).size == 0 for ch in (2, 3, 5))


def test_a_missing_segment_is_black_and_the_rest_stay_in_place() -> None:
    r = Reader()
    for p in stream(4, 860, skip={(1, 2, 7)}):
        r.add(p)
    want = expected(4, 1)
    want[16:24, 7 * 112: 8 * 112] = 0
    assert (r.image(1) == want).all()


def test_a_repeated_segment_replaces_the_first() -> None:
    r = Reader()
    pk = stream(3, 0)
    for p in pk:
        r.add(p)
    r.add(packet(64, 43 + 2, flat_segment(250, 14 * 2)))  # channel 1, scan 1, segment 2 again
    img = r.image(0)
    assert (img[8:16, 224:336] == 250).all()


def test_channels_share_one_extent() -> None:
    """A channel that starts late or ends early is padded to the others' scans, not cut to its own."""
    r = Reader()
    late = {(2, s, j) for s in range(2) for j in range(MCUS)} | {(2, 5, j) for j in range(MCUS)}
    for p in stream(6, 0, skip=late):
        r.add(p)
    imgs = [r.image(ch) for ch in (0, 1, 4)]
    assert {i.shape for i in imgs} == {(48, WIDTH)}
    assert (imgs[2][:16] == 0).all() and (imgs[2][40:] == 0).all() and (imgs[2][16:40] == expected(6, 2)[16:40]).all()


def test_a_segment_too_far_from_the_rest_is_dropped() -> None:
    """A span over 20,000 ids (a data error: no pass is that long) must not grow the image."""
    r = Reader()
    for p in stream(2, 0):
        r.add(p)
    before = (r.image(0).copy(), r.ch[0].first, r.ch[0].last)
    r.ch[0].rollover = 16384 * 40  # as if the count had wrapped 40 times: about 213,000 ids on
    r.add(packet(64, 100, flat_segment(99, 0)))
    assert (r.ch[0].first, r.ch[0].last) == before[1:] and (r.image(0) == before[0]).all()
