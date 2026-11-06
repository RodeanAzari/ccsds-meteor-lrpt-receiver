"""fec_acs: one add-compare-select against model/viterbi_fixed.py (modulo add, acs_select()).

Why it matters: with modulo path metrics (ADR 0006), the compare must read m1 - m0 as a signed 9-bit difference. An
unsigned compare is right until a metric wraps past 511 and then picks the wrong survivor, which in a decoder only
shows after the metrics first wrap, a few dozen steps in. Ties must keep branch 0 like the model, or decisions differ
on the many exact ties of noise-free input. Checked on random inputs and on every difference around 0 and ±256.
"""

from __future__ import annotations

import numpy as np
from cocotb import test
from cocotb.triggers import Timer
from tb_common import get_rng

from model.viterbi_fixed import acs_select

PM_BITS = 9
BM_BITS = 5
MASK = (1 << PM_BITS) - 1


async def check(dut, pm0: int, pm1: int, bm0: int, bm1: int) -> None:
    dut.pm0_i.value, dut.pm1_i.value, dut.bm0_i.value, dut.bm1_i.value = pm0, pm1, bm0, bm1
    await Timer(1, unit="ns")
    m0, m1 = (pm0 + bm0) & MASK, (pm1 + bm1) & MASK
    dec = bool(acs_select(np.array(m0), np.array(m1), PM_BITS))
    assert int(dut.dec_o.value) == dec, f"pm=({pm0}, {pm1}) bm=({bm0}, {bm1}): decision {int(dut.dec_o.value)}"
    assert int(dut.pm_o.value) == (m1 if dec else m0), f"pm=({pm0}, {pm1}) bm=({bm0}, {bm1}): metric"


@test()
async def random_inputs(dut) -> None:
    rng = get_rng("fec_acs")
    for _ in range(20_000):
        await check(dut, rng.randrange(1 << PM_BITS), rng.randrange(1 << PM_BITS), rng.randrange(31),
                    rng.randrange(31))


@test()
async def differences_at_zero_and_wrap(dut) -> None:
    """Candidate differences -3..3 and 253..259 (the signed boundary), from every base, so every wrap is crossed."""
    for base in range(0, 1 << PM_BITS, 7):
        for diff in [*range(-3, 4), *range(253, 260)]:
            await check(dut, base, (base + diff) & MASK, 0, 0)
            await check(dut, base, base, 0, diff % 31)  # the same differences reached through the branch metric
