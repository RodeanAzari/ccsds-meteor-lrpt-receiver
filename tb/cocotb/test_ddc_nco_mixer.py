"""ddc_nco_mixer: NCO + complex mixer, bit-exact against model/ddc_fixed.py nco() and mix().

Why it matters: the mixer moves the signal from the 100-250 kHz tuning offset to baseband. A wrong quadrant mirror,
a sign error in the complex multiply or a phase that slips one sample under backpressure would shift or mirror the
spectrum. The receiver might then still half-lock and "almost work" (CLAUDE.md §12), so exactness is checked here,
under stalls, at the default tuning word and at arbitrary words that visit every table phase.
"""

from __future__ import annotations

import numpy as np
from cocotb import test
from stream_tb import pack_iq, run_stream, unpack_iq

from model import ddc_fixed as m

IN_W, OUT_W = 10, 16


async def run(dut, i: np.ndarray, q: np.ndarray, word: int, name: str, p_valid: float, p_ready: float) -> None:
    exp_i, exp_q = m.mix(i, q, *m.nco(i.size, word))
    expected = list(zip(exp_i.tolist(), exp_q.tolist(), strict=True))

    def setup(dut) -> None:
        dut.freq_word_i.value = word

    await run_stream(
        dut, name, pack_iq(i, q, IN_W), expected, lambda d: unpack_iq(d, OUT_W), p_valid, p_ready, setup
    )


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
