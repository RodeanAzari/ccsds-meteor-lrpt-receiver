"""ddc_nco_mixer: NCO + complex mixer, bit-exact against model/ddc_fixed.py nco() and mix().

Why it matters: the mixer moves the signal from the 100-250 kHz tuning offset to baseband. A wrong quadrant mirror,
a sign error in the complex multiply or a phase that slips one sample under backpressure would shift or mirror the
spectrum. The receiver might then still half-lock and "almost work" (CLAUDE.md §12), so exactness is checked here,
under stalls, at the default tuning word and at arbitrary words that visit every table phase.
"""

from __future__ import annotations

import numpy as np
from cocotb import start_soon, test
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge
from tb_common import InOrderScoreboard, get_rng
from tb_common.axis import AxisBeat, AxisSink, AxisSource

from model import ddc_fixed as m

IN_W, OUT_W = 10, 16


def signed(v: int, bits: int) -> int:
    return v - (1 << bits) if v >> (bits - 1) else v


async def run(dut, i: np.ndarray, q: np.ndarray, word: int, name: str, p_valid: float, p_ready: float) -> None:
    start_soon(Clock(dut.clk_i, 10, unit="ns").start())
    rng = get_rng(name)
    dut.rst_i.value = 1
    dut.s_tvalid_i.value = 0
    dut.freq_word_i.value = word
    await ClockCycles(dut.clk_i, 3)
    dut.rst_i.value = 0

    cos, sin = m.nco(i.size, word)
    exp_i, exp_q = m.mix(i, q, cos, sin)
    sb = InOrderScoreboard(name)
    for a, b in zip(exp_i.tolist(), exp_q.tolist(), strict=True):
        sb.expect((a, b))

    def on_beat(frame: list[AxisBeat]) -> None:
        d = frame[0].data
        sb.observe((signed(d & 0xFFFF, OUT_W), signed(d >> OUT_W, OUT_W)))

    AxisSink(dut, dut.clk_i, "m_", rng=rng, p_ready=p_ready, callback=on_beat)
    src = AxisSource(dut, dut.clk_i, "s_", rng=rng, p_valid=p_valid)
    mask = (1 << IN_W) - 1
    await src.send(AxisBeat((int(a) & mask) | ((int(b) & mask) << IN_W)) for a, b in zip(i, q, strict=True))
    for _ in range(50):
        if sb.pending == 0:
            break
        await RisingEdge(dut.clk_i)
    sb.check_done()


@test()
async def default_tuning_backpressure(dut) -> None:
    """150 kHz at 1.024 MS/s (the default capture offset), DC-blocked noise-like input, random stalls on both sides."""
    rng = np.random.default_rng(2)
    n = 5000
    i = np.clip(np.round(60 * rng.standard_normal(n)), -510, 510).astype(np.int64)
    q = np.clip(np.round(60 * rng.standard_normal(n)), -510, 510).astype(np.int64)
    await run(dut, i, q, m.freq_word(150e3, 1.024e6), "mixer_150k", p_valid=0.6, p_ready=0.5)


@test()
async def arbitrary_words_full_scale(dut) -> None:
    """A Doppler-shifted word (phase truncation active) and a negative-frequency word, with full-scale s10 input.

    20,000 samples at an irrational-ish word visit all 4,096 table phases, so every quadrant mirror and every table
    entry on both read ports is compared. Full-scale inputs exercise the rounding at the largest products.
    """
    rng = np.random.default_rng(3)
    n = 20000
    i = rng.integers(-512, 512, n)
    q = rng.integers(-512, 512, n)
    word = m.freq_word(150e3 + 3371.7, 1.024e6)
    phases = (np.arange(n, dtype=np.int64) * word) & ((1 << m.PHASE_BITS) - 1)
    assert np.unique(phases >> (m.PHASE_BITS - m.LUT_PHASE_BITS)).size == 1 << m.LUT_PHASE_BITS
    await run(dut, i, q, word, "mixer_doppler", p_valid=0.9, p_ready=0.8)


@test()
async def negative_frequency(dut) -> None:
    """Tuned above the signal: a negative offset wraps to a large word and must rotate the other way."""
    rng = np.random.default_rng(4)
    n = 4000
    i = rng.integers(-512, 512, n)
    q = rng.integers(-512, 512, n)
    await run(dut, i, q, m.freq_word(-212.5e3, 1.024e6), "mixer_negative", p_valid=1.0, p_ready=1.0)
