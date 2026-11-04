"""ddc_ingest: cu8 -> s9 -> DC block, bit-exact against model/ddc_fixed.py.

Why it matters: every later block is checked against the bit-true model on the assumption that its input already
matches. A single LSB of difference here makes every downstream comparison fail for reasons unrelated to that block.
The DC block exists because the RTL-SDR adds a DC offset; the step test drives the worst case the fixed-point widths
were sized for (a full-scale DC step, output +-510), so an undersized accumulator or a missing saturation shows up.
"""

from __future__ import annotations

import numpy as np
from cocotb import start_soon, test
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge
from tb_common import InOrderScoreboard, get_rng
from tb_common.axis import AxisBeat, AxisSink, AxisSource

from model import ddc_fixed as m

OUT_W = 10


def signed(v: int, bits: int) -> int:
    return v - (1 << bits) if v >> (bits - 1) else v


async def run(dut, raw: np.ndarray, name: str, p_valid: float, p_ready: float) -> list[tuple[int, int]]:
    """Stream interleaved cu8 `raw` through the DUT; check every output against the model; return the outputs."""
    start_soon(Clock(dut.clk_i, 10, unit="ns").start())
    rng = get_rng(name)
    dut.rst_i.value = 1
    dut.s_tvalid_i.value = 0
    await ClockCycles(dut.clk_i, 3)
    dut.rst_i.value = 0

    i, q = m.ingest(raw)
    exp_i, exp_q = m.dc_block(i), m.dc_block(q)
    sb = InOrderScoreboard(name)
    for a, b in zip(exp_i.tolist(), exp_q.tolist(), strict=True):
        sb.expect((a, b))

    got: list[tuple[int, int]] = []

    def on_beat(frame: list[AxisBeat]) -> None:
        d = frame[0].data
        item = (signed(d & ((1 << OUT_W) - 1), OUT_W), signed(d >> OUT_W, OUT_W))
        got.append(item)
        sb.observe(item)

    AxisSink(dut, dut.clk_i, "m_", rng=rng, p_ready=p_ready, callback=on_beat)
    src = AxisSource(dut, dut.clk_i, "s_", rng=rng, p_valid=p_valid)
    words = (raw[0::2].astype(int) | (raw[1::2].astype(int) << 8)).tolist()
    await src.send(AxisBeat(w) for w in words)
    for _ in range(50):
        if sb.pending == 0:
            break
        await RisingEdge(dut.clk_i)
    sb.check_done()
    return got


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
