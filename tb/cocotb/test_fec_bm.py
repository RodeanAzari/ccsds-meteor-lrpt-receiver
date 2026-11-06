"""fec_bm: the four branch metrics for every pair of 4-bit soft symbols, against model/viterbi_fixed.branch_metric().

Why it matters: the branch metric is the decoder's only view of the channel. A metric that swaps the expected bit for
one rail, or loses the carry into bit 4 at the largest distances (15 + 15 = 30), still decodes clean signals and
quietly costs coding gain on noisy ones, which no clean-signal test would show. All 256 input pairs are checked.
"""

from __future__ import annotations

import numpy as np
from cocotb import test
from cocotb.triggers import Timer

from model.viterbi_fixed import branch_metric

SOFT_BITS = 4


@test()
async def all_input_pairs(dut) -> None:
    w = SOFT_BITS + 1
    for a in range(1 << SOFT_BITS):
        for b in range(1 << SOFT_BITS):
            dut.a_i.value = a
            dut.b_i.value = b
            await Timer(1, unit="ns")
            word = int(dut.bm_o.value)
            for k in range(4):
                got = (word >> (k * w)) & ((1 << w) - 1)
                want = int(branch_metric(np.array(a), np.array(b), np.array(bool(k & 2)), np.array(bool(k & 1)),
                                         SOFT_BITS))
                assert got == want, f"a={a} b={b} expected (g1, g2)=({k >> 1}, {k & 1}): {got} != {want}"
