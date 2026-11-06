"""fec_acs_array: 64-state ACS, every decision row bit-exact against model/viterbi_fixed.py acs().

Why it matters: the decision rows are all the traceback sees. A wrong predecessor wiring or a swapped G1/G2 tap set
gives rows that still look random, and the decoder fails only at the very end, as a BER curve that is too high.
Comparing every row against the model localizes such a bug to this block. The noisy runs are checked to wrap the 9-bit
path metrics many times, the case ADR 0006 relies on. Full-scale symbols give the largest metric spread (noise
shrinks it). Random input gaps and output stalls check that a held row never advances the metrics twice.
"""

from __future__ import annotations

import numpy as np
from cocotb import test
from fec_vectors import SOFT_BITS, coded_symbols, pairs
from stream_tb import run_stream

from model.coding import conv_encode
from model.viterbi_fixed import acs, path_metric_bits

PM_BITS = path_metric_bits(SOFT_BITS)


async def run(dut, u: np.ndarray, name: str, p_valid: float, p_ready: float, check_wraps: bool = True) -> int:
    # Every path gains at least the step's smallest branch metric, so the metrics wrap at least this many times.
    a, b = u[0::2], u[1::2]
    floor = int(np.minimum(a, 15 - a).sum() + np.minimum(b, 15 - b).sum())
    assert not check_wraps or floor >= 10 << PM_BITS, f"wraps not proven: bound {floor >> PM_BITS}"
    decisions, _, spread = acs(u[np.newaxis, :], SOFT_BITS, PM_BITS)
    rows = [int(np.packbits(d[0][::-1].astype(np.uint8)).view(">u8")[0]) for d in decisions]
    await run_stream(dut, name, pairs(u), rows, int, p_valid, p_ready)
    dut._log.info("%d steps bit-exact; metrics wrap >= %d times; spread %d (ADR 0006 bound 180)", len(rows),
                  floor >> PM_BITS, spread)
    return spread


@test()
async def noisy_backpressure(dut) -> None:
    """0 dB, where the decoder makes errors, so survivors switch often."""
    await run(dut, coded_symbols(4000, 0.0, 41)[1], "fec_acs_array", 0.7, 0.6)


@test()
async def full_scale_spread(dut) -> None:
    """Full-scale symbols (0 or 15) with 5% flipped: wrong paths fall 30 behind per step, the widest spread.

    Unflipped symbols cost the right path nothing, so the wrap bound proves nothing here; the noisy runs cover wraps.
    """
    rng = np.random.default_rng(43)
    u = conv_encode(rng.integers(0, 2, 4000, dtype=np.uint8)).astype(np.int64) * 15
    flip = rng.random(u.size) < 0.05
    u[flip] = 15 - u[flip]
    spread = await run(dut, u, "fec_acs_array_spread", 0.7, 0.6, check_wraps=False)
    assert spread >= 120, "the run never reached the full-scale spread"


@test()
async def clean_full_rate(dut) -> None:
    """6 dB, no stalls: one step per clock."""
    await run(dut, coded_symbols(4000, 6.0, 42)[1], "fec_acs_array_rate", 1.0, 1.0)
