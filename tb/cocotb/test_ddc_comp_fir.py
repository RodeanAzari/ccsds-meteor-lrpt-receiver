"""ddc_comp_fir: 31-tap CIC droop compensation, bit-exact against model/ddc_fixed.py comp_fir().

Why it matters: the FIR undoes the CIC's passband droop before the matched filter. A tap read from the wrong
address, an off-by-one in the history or an accumulator that drops a product changes the filter's shape, and the
RRC matched filter downstream then no longer matches the transmit pulse. Impulses read the taps back one by one;
full-scale alternating input drives the accumulator to its largest value and exercises saturation.
"""

from __future__ import annotations

import numpy as np
from cocotb import test
from stream_tb import pack_iq, run_stream, unpack_iq

from model import ddc_fixed as m
from model.receiver import RxConfig

W = 16
TAPS = m.comp_taps(RxConfig())


async def run(dut, i: np.ndarray, q: np.ndarray, name: str, p_valid: float, p_ready: float) -> list[tuple[int, int]]:
    expected = list(zip(m.comp_fir(i, TAPS).tolist(), m.comp_fir(q, TAPS).tolist(), strict=True))
    return await run_stream(dut, name, pack_iq(i, q, W), expected, lambda d: unpack_iq(d, W), p_valid, p_ready)


@test()
async def impulse_reads_back_taps(dut) -> None:
    """An impulse of 2^15 - 1 on I and -2^15 on Q: the output is each tap, scaled, in order (and mirrored on Q)."""
    n = 2 * TAPS.size
    i = np.zeros(n, dtype=np.int64)
    q = np.zeros(n, dtype=np.int64)
    i[0], q[0] = 32767, -32768
    got = await run(dut, i, q, "fir_impulse", 1.0, 1.0)
    peak = int(np.argmax([abs(a) for a, _ in got]))
    assert peak == TAPS.size // 2, f"impulse response peaks at {peak}, not the centre tap {TAPS.size // 2}"


@test()
async def random_backpressure(dut) -> None:
    """CIC-output-level noise with random stalls on both sides."""
    rng = np.random.default_rng(7)
    n = 3000
    i = np.round(3000 * rng.standard_normal(n)).astype(np.int64)
    q = np.round(3000 * rng.standard_normal(n)).astype(np.int64)
    await run(dut, i, q, "fir_noise", 0.5, 0.5)


@test()
async def worst_case_saturates(dut) -> None:
    """Input signs matched to the taps (+-32767): sum |h| = 1.98 overflows s16, so the output must clip, not wrap."""
    sign = np.sign(TAPS[::-1]).astype(np.int64)
    i = np.tile(32767 * sign, 4)
    q = -i
    got = await run(dut, i, q, "fir_saturate", 0.8, 0.8)
    assert (32767, -32768) in got, "worst-case input never reached the saturation limits"
