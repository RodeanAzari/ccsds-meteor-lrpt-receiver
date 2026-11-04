"""ddc_cic: CIC /4 order 3, bit-exact against model/ddc_fixed.py cic_decimate().

Why it matters: the integrators wrap by design and the output is exact only if every register is the full
Hogenauer width and the decimation phase matches the model (keep inputs 3, 7, 11, ...). An undersized register wraps
silently (CLAUDE.md §12) and a phase slip under backpressure changes every output, so both show up as mismatches.
Full-scale constants check the gain 64 is removed exactly: a DC input must come out unchanged.
"""

from __future__ import annotations

import numpy as np
from cocotb import test
from stream_tb import pack_iq, run_stream, unpack_iq

from model import ddc_fixed as m

W = 16


async def run(dut, i: np.ndarray, q: np.ndarray, name: str, p_valid: float, p_ready: float) -> list[tuple[int, int]]:
    expected = list(zip(m.cic_decimate(i).tolist(), m.cic_decimate(q).tolist(), strict=True))
    return await run_stream(dut, name, pack_iq(i, q, W), expected, lambda d: unpack_iq(d, W), p_valid, p_ready)


@test()
async def random_full_scale_backpressure(dut) -> None:
    """Uniform full-scale s16 input (worst case for register growth), random stalls on both sides."""
    rng = np.random.default_rng(5)
    n = 16000
    await run(dut, rng.integers(-32768, 32768, n), rng.integers(-32768, 32768, n), "cic_random", 0.7, 0.4)


@test()
async def full_scale_dc(dut) -> None:
    """Constant -32768 / +32767: after the 3-stage transient the output equals the input (gain removed exactly)."""
    n = 400
    i = np.full(n, -32768, dtype=np.int64)
    q = np.full(n, 32767, dtype=np.int64)
    got = await run(dut, i, q, "cic_dc", 1.0, 1.0)
    assert got[-1] == (-32768, 32767), f"DC gain not unity: {got[-1]}"


@test()
async def mixer_range_noise(dut) -> None:
    """A signal at the mixer's real output level (|x| <= 11,563), the case the downstream chain sees."""
    rng = np.random.default_rng(6)
    n = 8000
    i = np.clip(np.round(3000 * rng.standard_normal(n)), -11563, 11563).astype(np.int64)
    q = np.clip(np.round(3000 * rng.standard_normal(n)), -11563, 11563).astype(np.int64)
    await run(dut, i, q, "cic_noise", 0.8, 0.8)
