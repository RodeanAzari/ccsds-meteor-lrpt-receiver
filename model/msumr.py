"""MSU-MR images from space packets: the golden model for the optional image step (buildplan §4).

docs/signal-spec.md "MSU-MR image packets" is the spec: the behaviour of the installed SatDump build (b79af48),
quirks included, so that the same packets give the same pixels. Written from that description and ITU-T T.81 (the
JPEG standard), not ported from SatDump (GPL-3; this repository is MIT).

    segment_pixels(data)   one packet's data field -> 8 x 112 pixels, or None when SatDump would drop it
    Reader                 places segments by sequence count, per channel; image(ch) -> (rows, 1568) uint8
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

APID_CHANNEL = {64 + c: c for c in range(6)}  # signal-spec.md: APIDs 64-69 are channels 1-6
MCUS = 14  # MCUs per segment
WIDTH = 1568  # 14 segments x 14 MCUs x 8 pixels
PACKETS_PER_SCAN = 43  # 14 segments x 3 channels + 1 telemetry
SEQ_MOD = 1 << 14
MAX_ID = 20_000  # ids at or above are dropped
U32 = (1 << 32) - 1

# T.81 Table K.1, luminance quantization, natural (row-major) order
K1 = np.array([16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55,
               14, 13, 16, 24, 40, 57, 69, 56, 14, 17, 22, 29, 51, 87, 80, 62,
               18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104, 113, 92,
               49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98, 112, 100, 103, 99], dtype=np.float32)


def _zigzag() -> npt.NDArray[np.int64]:
    """T.81 Figure A.6: natural position of the k-th coefficient in zigzag order."""
    order = sorted(((r, c) for r in range(8) for c in range(8)),
                   key=lambda rc: (rc[0] + rc[1], rc[0] if (rc[0] + rc[1]) % 2 else rc[1]))
    return np.array([r * 8 + c for r, c in order], dtype=np.int64)


ZIGZAG = _zigzag()

# T.81 Tables K.3 and K.5: luminance DC and AC codes as BITS (codes per length 1..16) and HUFFVAL
DC_BITS = [0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0]
DC_VALS = list(range(12))
AC_BITS = [0, 2, 1, 3, 3, 2, 4, 3, 5, 5, 4, 4, 0, 0, 1, 0x7D]
AC_VALS = [
    0x01, 0x02, 0x03, 0x00, 0x04, 0x11, 0x05, 0x12, 0x21, 0x31, 0x41, 0x06, 0x13, 0x51, 0x61, 0x07,
    0x22, 0x71, 0x14, 0x32, 0x81, 0x91, 0xA1, 0x08, 0x23, 0x42, 0xB1, 0xC1, 0x15, 0x52, 0xD1, 0xF0,
    0x24, 0x33, 0x62, 0x72, 0x82, 0x09, 0x0A, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x25, 0x26, 0x27, 0x28,
    0x29, 0x2A, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3A, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48, 0x49,
    0x4A, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59, 0x5A, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68, 0x69,
    0x6A, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78, 0x79, 0x7A, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89,
    0x8A, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98, 0x99, 0x9A, 0xA2, 0xA3, 0xA4, 0xA5, 0xA6, 0xA7,
    0xA8, 0xA9, 0xAA, 0xB2, 0xB3, 0xB4, 0xB5, 0xB6, 0xB7, 0xB8, 0xB9, 0xBA, 0xC2, 0xC3, 0xC4, 0xC5,
    0xC6, 0xC7, 0xC8, 0xC9, 0xCA, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0xD9, 0xDA, 0xE1, 0xE2,
    0xE3, 0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xE9, 0xEA, 0xF1, 0xF2, 0xF3, 0xF4, 0xF5, 0xF6, 0xF7, 0xF8,
    0xF9, 0xFA,
]
PEEK = 16  # longest code


def huffman_codes(bits: list[int], vals: list[int]) -> dict[tuple[int, int], int]:
    """T.81 Annex C: (length, code) -> symbol, codes assigned in canonical order."""
    codes, code, k = {}, 0, 0
    for length, n in enumerate(bits, start=1):
        for _ in range(n):
            codes[(length, code)] = vals[k]
            code, k = code + 1, k + 1
        code <<= 1
    return codes


def _lut(codes: dict[tuple[int, int], int]) -> tuple[npt.NDArray[np.int16], npt.NDArray[np.int8]]:
    """16-bit peek -> (symbol, code length); length 0 where no code is a prefix of the peek."""
    sym, ln = np.full(1 << PEEK, -1, dtype=np.int16), np.zeros(1 << PEEK, dtype=np.int8)
    for (length, code), s in codes.items():
        lo = code << (PEEK - length)
        sym[lo: lo + (1 << (PEEK - length))] = s
        ln[lo: lo + (1 << (PEEK - length))] = length
    return sym, ln


DC_LUT = _lut(huffman_codes(DC_BITS, DC_VALS))
AC_LUT = _lut(huffman_codes(AC_BITS, AC_VALS))


def quant_table(qf: int) -> npt.NDArray[np.int64]:
    """K.1 scaled by the quality factor, in 32-bit float as SatDump computes it (signal-spec.md)."""
    f = np.float32(qf)
    f = np.float32(5000) / f if 20 < qf < 50 else np.float32(200) - np.float32(2) * f
    q = (f / np.float32(100) * K1 + np.float32(0.5)).astype(np.int64)  # astype truncates toward zero, like C
    return np.maximum(q, 1)


class _Bits:
    """MSB-first bit reader with SatDump's end rule: a code or its magnitude bits must fit in what is left."""

    def __init__(self, data: bytes) -> None:
        self.v = int.from_bytes(data, "big")
        self.n = 8 * len(data)
        self.pos = 0

    def peek16(self) -> int:
        left = self.n - self.pos
        if left >= PEEK:
            return (self.v >> (left - PEEK)) & 0xFFFF
        return (self.v & ((1 << left) - 1)) << (PEEK - left)

    def symbol(self, lut: tuple[npt.NDArray[np.int16], npt.NDArray[np.int8]]) -> int | None:
        sym, ln = lut
        p = self.peek16()
        length = int(ln[p])
        if length == 0 or length > self.n - self.pos:
            return None
        self.pos += length
        return int(sym[p])

    def magnitude(self, size: int) -> int | None:
        """T.81 F.12 EXTEND: size bits, a leading 0 means negative. None if fewer bits are left."""
        if size > self.n - self.pos:
            return None
        if size == 0:
            return 0
        left = self.n - self.pos
        v = (self.v >> (left - size)) & ((1 << size) - 1)
        self.pos += size
        return v if v >> (size - 1) else v - ((1 << size) - 1)


def decode_coefficients(data: bytes) -> tuple[npt.NDArray[np.int64], int]:
    """Entropy-coded data -> (14, 64) quantized coefficients in natural order, and how many MCUs decoded (0 means
    the segment is invalid; fewer than 14 means decoding stopped there and the rest stay 0)."""
    bits = _Bits(data)
    out = np.zeros((MCUS, 64), dtype=np.int64)
    dc = 0
    for m in range(MCUS):
        cat = bits.symbol(DC_LUT)
        diff = None if cat is None else bits.magnitude(cat)
        if diff is None:
            return out, m
        dc += diff
        zz = [dc] + [0] * 63  # zigzag order
        index, counted = 1, 0
        while counted < 63:
            rs = bits.symbol(AC_LUT)
            if rs is None:
                return out, m
            run, size = rs >> 4, rs & 0xF
            if rs == 0x00:  # EOB
                counted += 1
                break
            value = 0 if rs == 0xF0 else bits.magnitude(size)  # ZRL: 16 zeros, no magnitude bits
            if value is None:
                return out, m
            counted += run + 1
            if index + run + 1 >= 64:  # would reach index 64: the block ends (coefficient 63 is never set)
                break
            zz[index + run] = value
            index += run + 1
        out[m, ZIGZAG] = zz
    return out, MCUS


W1, W2, W3, W5, W6, W7, R2 = 2841, 2676, 2408, 1609, 1108, 565, 181  # 2048*sqrt(2)*cos(k*pi/16); 256/sqrt(2)


def _idct_1d(x: list[npt.NDArray[np.int64]], pass_: int) -> list[npt.NDArray[np.int64]]:
    """One 1-D pass of the fixed-point IDCT (Wang 1984, as in Go's image/jpeg). x: the 8 inputs in natural order;
    pass_ 0 = rows, 1 = columns (different prescale and rounding)."""
    x0, x1, x2, x3, x4, x5, x6, x7 = x
    if pass_ == 0:
        a0, a1, r = (x0 << 11) + 128, x4 << 11, 0
    else:
        a0, a1, r = (x0 << 8) + 8192, x4 << 8, 4
    s = 0 if pass_ == 0 else 3
    a2, a3, a4, a5, a6, a7 = x6, x2, x1, x7, x5, x3
    t = W7 * (a4 + a5) + r
    a4, a5 = (t + (W1 - W7) * a4) >> s, (t - (W1 + W7) * a5) >> s
    t = W3 * (a6 + a7) + r
    a6, a7 = (t - (W3 - W5) * a6) >> s, (t - (W3 + W5) * a7) >> s
    t, a0 = a0 + a1, a0 - a1
    a1 = W6 * (a3 + a2) + r
    a2, a3 = (a1 - (W2 + W6) * a2) >> s, (a1 + (W2 - W6) * a3) >> s
    a1, a4 = a4 + a6, a4 - a6
    a6, a5 = a5 + a7, a5 - a7
    a7, t = t + a3, t - a3
    a3, a0 = a0 + a2, a0 - a2
    a2, a4 = (R2 * (a4 + a5) + 128) >> 8, (R2 * (a4 - a5) + 128) >> 8
    sh = 8 if pass_ == 0 else 14
    return [(a7 + a1) >> sh, (a3 + a2) >> sh, (a0 + a4) >> sh, (t + a6) >> sh,
            (t - a6) >> sh, (a0 - a4) >> sh, (a3 - a2) >> sh, (a7 - a1) >> sh]


def idct(coef: npt.NDArray[np.int64]) -> npt.NDArray[np.int64]:
    """(n, 64) dequantized coefficients, natural order -> (n, 64) IDCT output (before the +128)."""
    b = coef.reshape(-1, 8, 8).astype(np.int64)
    rows = _idct_1d([b[:, :, k] for k in range(8)], pass_=0)
    flat = np.all(b[:, :, 1:] == 0, axis=2)  # row shortcut: all AC zero -> DC << 3 across the row
    h = np.stack([np.where(flat, b[:, :, 0] << 3, r) for r in rows], axis=2)
    cols = _idct_1d([h[:, k, :] for k in range(8)], pass_=1)
    return np.stack(cols, axis=1).reshape(-1, 64)


@dataclass
class Segment:
    mcun: int
    pixels: npt.NDArray[np.uint8]  # (8, 112)


def segment_pixels(data: bytes) -> Segment | None:
    """A packet's data field (after the 6-byte primary header) -> its segment, or None if SatDump drops it."""
    if len(data) <= 14 or data[9] != 0 or data[10] & 0x0F or (data[11] << 8 | data[12]) != 0xFFF0:
        return None
    coef, done = decode_coefficients(data[14:])
    if done == 0:
        return None
    blocks = idct(coef * quant_table(data[13])[np.newaxis, :])
    blocks[done:] = -128  # MCUs after a decode failure stay 0
    px = np.clip(blocks + 128, 0, 255).astype(np.uint8).reshape(MCUS, 8, 8)
    return Segment(data[8], px.transpose(1, 0, 2).reshape(8, MCUS * 8))


@dataclass
class _Channel:
    segments: dict[int, Segment] = field(default_factory=dict)
    packets: dict[int, bytes] = field(default_factory=dict)  # the packet each stored segment came from
    first: int = U32
    last: int = 0
    rollover: int = 0
    last_seq: int = 0
    offset: int = U32  # unset: no valid segment yet


def _floor14(x: int) -> int:
    return x - x % MCUS


class Reader:
    """Places each channel's segments by sequence count and builds the images on one shared extent
    (signal-spec.md "Placing segments", "Image extent"; SatDump b79af48)."""

    def __init__(self) -> None:
        self.ch = [_Channel() for _ in range(6)]

    def add(self, packet: bytes) -> None:
        """One space packet, primary header included."""
        apid = (packet[0] & 0x07) << 8 | packet[1]
        if apid not in APID_CHANNEL:
            return
        seg = segment_pixels(packet[6:])
        if seg is None:
            return
        c = self.ch[APID_CHANNEL[apid]]
        seq = (packet[2] & 0x3F) << 8 | packet[3]
        mcu_count = seg.mcun // MCUS
        if c.last_seq > seq and c.last_seq > 13926 and seq < 2458:
            c.rollover += SEQ_MOD
        if c.offset == U32:
            mcu_seq = (seq + (SEQ_MOD if mcu_count > seq else 0) - mcu_count) & U32
            c.offset = ((mcu_seq + c.rollover) & U32) % PACKETS_PER_SCAN
        seg_id = (((seq + c.rollover - c.offset) & U32) // PACKETS_PER_SCAN * MCUS + mcu_count) & U32
        first, last = min(c.first, seg_id), max(c.last, seg_id)
        if last - first > MAX_ID:  # both unsigned, last >= first here
            return
        c.first, c.last, c.last_seq = first, last, seq
        c.segments[seg_id] = seg
        c.packets[seg_id] = packet

    def extent(self, channel: int) -> tuple[int, int]:
        """(first id, end id) of `channel`'s image, both multiples of 14; scans from first up to, not including, end."""
        low = 6  # channel with the smallest offset below 43, lowest-numbered on a tie
        for i, c in enumerate(self.ch):
            if c.offset < (PACKETS_PER_SCAN if low == 6 else self.ch[low].offset):
                low = i
        lowest_transmitted = 0  # SatDump sets it on the first pass of its loop, data or not
        f, e, fb, eb, fa, ea = U32, 0, U32, 0, U32, 0
        for i, c in enumerate(self.ch):
            if c.offset == U32:
                continue
            f, e = min(f, c.first), max(e, c.last)
            if i < low:
                fb, eb = min(fb, c.first), max(eb, c.last)
            else:
                fa, ea = min(fa, c.first), max(ea, c.last)
        if lowest_transmitted != low:
            a = _floor14(fb) >= _floor14(fa)
            b = _floor14(eb) < _floor14(ea)
            if channel < low:
                f, e = (f - MCUS if a else f) & U32, (e - MCUS if b else e) & U32
            else:
                f, e = (f if a else f + MCUS) & U32, (e if b else e + MCUS) & U32
        e = (e + MCUS) & U32
        if self.ch[channel].first == U32:
            f = 0
        if self.ch[channel].last == 0:
            e = 0
        return _floor14(f), _floor14(e)

    def image(self, channel: int) -> npt.NDArray[np.uint8]:
        """(rows, 1568) pixels; 0 rows when the channel had no segment."""
        first, end = self.extent(channel)
        scans = ((end - first) & U32) // MCUS
        segs = self.ch[channel].segments
        img = np.zeros((scans * 8, WIDTH), dtype=np.uint8)
        for s in range(scans):
            for j in range(MCUS):
                seg = segs.get((first + s * MCUS + j) & U32)
                if seg is not None:
                    img[s * 8: s * 8 + 8, j * MCUS * 8: (j + 1) * MCUS * 8] = seg.pixels
        return img
