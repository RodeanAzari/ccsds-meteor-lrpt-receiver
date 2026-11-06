"""fec_traceback: decision rows in, decoded bits out, bit-exact against model/viterbi_fixed.traceback_sliding().

Why it matters: the traceback turns the ACS decisions into data. Off-by-one errors here (one row too few, the wrong
end of the walk, a ring pointer that overwrites a row still needed) don't stop it decoding: the output is still mostly
right, so a BER-only check passes. Each one shifts or corrupts bits in ways only an exact comparison shows. The depth
is a register (ADR 0008), so a second depth checks that nothing assumes 96. The decoded bits are also compared with
the bits sent, so a test that agreed with a broken model would still fail.
"""

from __future__ import annotations

import numpy as np
from cocotb import test
from cocotb.utils import get_sim_time
from fec_vectors import SOFT_BITS, coded_symbols
from stream_tb import run_stream

from model.viterbi_fixed import TRACEBACK_DEPTH, acs, path_metric_bits, traceback_sliding


def rows_of(decisions: np.ndarray) -> list[int]:
    return [int(np.packbits(d[0][::-1].astype(np.uint8)).view(">u8")[0]) for d in decisions]


async def run(dut, n_bits: int, ebn0_db: float, depth: int, seed: int, name: str, p_valid: float,
              p_ready: float) -> tuple[int, float]:
    sent, u = coded_symbols(n_bits, ebn0_db, seed)
    decisions, best, _ = acs(u[np.newaxis, :], SOFT_BITS, path_metric_bits(SOFT_BITS))
    want = traceback_sliding(decisions, np.zeros_like(best), depth)[0]
    t0 = get_sim_time("ns")
    got = await run_stream(dut, name, rows_of(decisions), want.tolist(), int, p_valid, p_ready,
                           lambda d: setattr(d.depth_i, "value", depth), drain_cycles=4 * depth)
    clocks = (get_sim_time("ns") - t0) / 10 / len(rows_of(decisions))
    errors = int(np.count_nonzero(np.array(got) != sent[: len(got)]))
    dut._log.info("depth %d: %d bits bit-exact; %d differ from the %d sent; %.1f clocks per row", depth, len(got),
                  errors, len(got), clocks)
    return errors, clocks


@test()
async def depth_96_backpressure(dut) -> None:
    """3 dB, ADR 0008's depth, random input gaps and output stalls."""
    errors, _ = await run(dut, 3000, 3.0, TRACEBACK_DEPTH, 51, "fec_traceback", 0.7, 0.6)
    assert errors < 30, "far more errors than the decoder makes at 3 dB: bits are misaligned"


@test()
async def depth_35_full_rate(dut) -> None:
    """A different depth (the low end of buildplan §3.6's range), clean signal, no stalls: depth + 3 clocks per bit."""
    errors, clocks = await run(dut, 3000, 6.0, 35, 52, "fec_traceback_rate", 1.0, 1.0)
    assert errors == 0, "a clean 6 dB signal must decode without error"
    assert clocks < 35 + 4, f"{clocks:.1f} clocks per bit"
