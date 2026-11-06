"""fec_soft_quant: {Q, I} sync output in, the 4-bit serial soft stream out, bit-exact against the model.

Why it matters: taking I on odd beats instead of even feeds the correlator and Viterbi the wrong rail at every symbol,
and a quantizer that wraps instead of saturating turns the strongest symbols into the most confident wrong ones.
"""

from __future__ import annotations

import numpy as np
from cocotb import test
from stream_tb import pack_iq, run_stream

from model.sync_fixed import serial
from model.viterbi_fixed import quantize


@test()
async def rails_alternate_and_saturate_under_backpressure(dut) -> None:
    rng = np.random.default_rng(71)
    n = 4000
    # Mostly in range, plus full-scale rails that must saturate, and every step boundary.
    i = rng.integers(-12_000, 12_000, n)
    q = rng.integers(-12_000, 12_000, n)
    i[:64] = np.array([-32768, 32767] * 32)
    q[64:128] = np.array([32767, -32768] * 32)
    i[128:160] = np.arange(-16, 16) * 1024
    q[160:192] = np.arange(-16, 16) * 1024 - 1
    want = quantize(serial(i, q), 4, 10)
    assert {0, 15} <= set(want.tolist())
    await run_stream(dut, "fec_soft_quant", pack_iq(i, q, 16), want.tolist(), int, 0.7, 0.6)
