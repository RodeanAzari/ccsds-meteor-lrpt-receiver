"""Bit-true model of the RTL after the Viterbi (ADR 0012): decoded window bits to CADUs with their status.

For each Viterbi window (framesync_fixed.decode_windows()): the frame is bits PRE/2 .. PRE/2 + 8,191 and NRZ-M
starts from bit PRE/2 - 1; then the ASM check, derandomizer and RS (coding.frame_to_cadu()). Out: 1,024 bytes per
CADU, with a status word (`status_word()`) that the RTL carries on every byte's tuser:

    [2:0] {flywheel, swap, alternate} (the window's flags, fec_framesync m_tuser)   [8:3] ASM bit errors
    [14:9], [20:15], [26:21], [32:27] codewords 0..3: {fail, corrected[4:0]} (count 0 when fail; rs_decoder tuser)
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from model.coding import CADU_BITS, RS_INTERLEAVE, Bits, frame_to_cadu
from model.framesync_fixed import PRE_SYMBOLS, Window

FRAME_FIRST_BIT = PRE_SYMBOLS // 2  # bit index of the frame in its window (ADR 0010 amendment)
STATUS_BITS = 3 + 6 + 6 * RS_INTERLEAVE


@dataclass(frozen=True)
class CaduOut:
    data: npt.NDArray[np.uint8]  # 1,024 bytes: ASM as received, body derandomized and RS-corrected
    alternate: bool
    swap: bool
    flywheel: bool
    asm_errors: int
    corrections: list[int]  # per codeword; -1 = uncorrectable

    def status_word(self) -> int:
        word = int(self.alternate) | int(self.swap) << 1 | int(self.flywheel) << 2 | self.asm_errors << 3
        for c, count in enumerate(self.corrections):
            field = 0x20 if count < 0 else count
            word |= field << (9 + 6 * c)
        return word


def cadus_from_windows(bits: Bits, wins: list[Window], writeback: bool = True) -> list[CaduOut]:
    """bits: decode_windows(wins), one row per window. writeback: coding.frame_to_cadu()."""
    out = []
    for row, w in zip(bits, wins, strict=True):
        data, asm_errors, corrections = frame_to_cadu(
            row[FRAME_FIRST_BIT : FRAME_FIRST_BIT + CADU_BITS], int(row[FRAME_FIRST_BIT - 1]), writeback
        )
        out.append(CaduOut(data, w.alternate, w.swap, w.flywheel, asm_errors, corrections))
    return out
