"""ddc_ingest: cu8 -> s9 -> DC block, bit-exact against model/ddc_fixed.py.

Why it matters: every later block is checked against the bit-true model on the assumption that its input already
matches. A single LSB of difference here makes every downstream comparison fail for reasons unrelated to that block.
The DC block exists because the RTL-SDR adds a DC offset; the step test drives the worst case the fixed-point widths
were sized for (a full-scale DC step, output +-510), so an undersized accumulator or a missing saturation shows up.
"""

from __future__ import annotations

import numpy as np
from cocotb import test
from stream_tb import run_stream, unpack_iq

from model import ddc_fixed as m

OUT_W = 10


async def run(dut, raw: np.ndarray, name: str, p_valid: float, p_ready: float) -> list[tuple[int, int]]:
    i, q = m.ingest(raw)
    expected = list(zip(m.dc_block(i).tolist(), m.dc_block(q).tolist(), strict=True))
    words = (raw[0::2].astype(int) | (raw[1::2].astype(int) << 8)).tolist()  # {Q_u8, I_u8}
    return await run_stream(dut, name, words, expected, lambda d: unpack_iq(d, OUT_W), p_valid, p_ready)


@test()
async def offset_noise_backpressure(dut) -> None:
    """RTL-SDR-like input: noise on a DC offset, random tvalid gaps and tready stalls. The offset must go away."""
    rng = np.random.default_rng(1)
    n = 6000
    raw = np.clip(np.round(150 + 20 * rng.standard_normal(2 * n)), 0, 255).astype(np.uint8)
    got = await run(dut, raw, "ingest_noise", p_valid=0.6, p_ready=0.5)
    tail = np.array(got[-1000:], dtype=float)
    # Input offset is 2*150 - 255 = 45 LSB; after ~5 time constants (5 * 1024 samples) it must be close to zero.
    assert np.all(np.abs(tail.mean(axis=0)) < 4.0), f"DC not removed: tail mean {tail.mean(axis=0)}"


@test()
async def full_scale_dc_steps(dut) -> None:
    """Rail steps 0 <-> 255 held long enough to settle: the +-510 worst case the s10 output was sized for."""
    n_seg, seg = 4, 16000  # 15.6 time constants (1024 samples each): the previous step has fully settled
    level = np.repeat(np.array([0, 255] * (n_seg // 2), dtype=np.uint8), seg)
    raw = np.empty(2 * level.size, dtype=np.uint8)
    raw[0::2], raw[1::2] = level, 255 - level  # I and Q step in opposite directions
    got = await run(dut, raw, "ingest_steps", p_valid=1.0, p_ready=1.0)
    peak = max(max(abs(a), abs(b)) for a, b in got)
    # A step of 510 on a settled output: the residual is under 2^-15 of the previous step, so the peak is 509 or 510.
    assert peak >= 509, f"expected a settled full-scale step to reach ~510, got {peak}"
