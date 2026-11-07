"""fec_frame_extract: the frame bits of each Viterbi window, NRZ-M decoded, with that window's flags.

Why it matters: the frame starts at a fixed bit of its window (ADR 0010 amendment) and NRZ-M needs the bit before
it; one bit off in either and every frame fails its ASM. The flags (phase hypothesis, flywheel) come from the other
end of the Viterbi and must leave with the right frame, however far ahead the Viterbi's input runs.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from cocotb import start_soon, test
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge
from tb_common import InOrderScoreboard, get_rng
from tb_common.axis import AxisBeat, AxisSink, AxisSource

from model.coding import CADU_BITS, nrzm_decode
from model.framesync_fixed import WINDOW_SYMBOLS

STEPS = WINDOW_SYMBOLS // 2
FIRST = 64


async def _start(dut: Any) -> None:
    start_soon(Clock(dut.clk_i, 10, unit="ns").start())
    dut.rst_i.value = 1
    dut.s_tvalid_i.value = 0
    dut.win_hs_i.value = 0
    dut.win_last_i.value = 0
    dut.win_tuser_i.value = 0
    await ClockCycles(dut.clk_i, 3)
    dut.rst_i.value = 0


async def _window_beats(dut: Any, flags: int, beats: int = 3) -> None:
    """A short window on the tap: first beat carries the flags, last beat flagged last."""
    for i in range(beats):
        dut.win_hs_i.value = 1
        dut.win_tuser_i.value = flags
        dut.win_last_i.value = int(i == beats - 1)
        await RisingEdge(dut.clk_i)
    dut.win_hs_i.value = 0


@test()
async def frames_and_flags_match_the_model(dut: Any) -> None:
    await _start(dut)
    windows = 5
    rng = np.random.default_rng(3)
    bits = rng.integers(0, 2, windows * STEPS).astype(np.uint8)
    flags = [int(f) for f in rng.integers(0, 8, windows)]
    sb = InOrderScoreboard("extract")
    for w in range(windows):
        row = bits[w * STEPS : (w + 1) * STEPS]
        sb.expect((nrzm_decode(row[FIRST : FIRST + CADU_BITS], int(row[FIRST - 1])).tolist(), flags[w]))
    got = [0]

    def on_frame(frame: list[AxisBeat]) -> None:
        assert len({b.user for b in frame}) == 1
        sb.observe(([int(b.data) for b in frame], int(frame[0].user or 0)))
        got[0] += 1

    trng = get_rng("extract")
    src = AxisSource(dut, dut.clk_i, "s_", rng=trng, p_valid=0.8)
    AxisSink(dut, dut.clk_i, "m_", rng=trng, p_ready=0.6, callback=on_frame)
    # The Viterbi's input runs ahead of its output: the first two windows' flags arrive before any bit.
    await _window_beats(dut, flags[0])
    await _window_beats(dut, flags[1])

    async def feed_tap() -> None:
        # Window w+2's first beat enters the Viterbi while window w comes out.
        for w in range(2, windows):
            while got[0] < w - 1:
                await RisingEdge(dut.clk_i)
            await _window_beats(dut, flags[w])

    start_soon(feed_tap())
    await src.send([AxisBeat(int(b)) for b in bits])
    for _ in range(10_000):
        if got[0] == windows:
            break
        await RisingEdge(dut.clk_i)
    assert got[0] == windows
    sb.check_done()
    assert int(dut.flag_ovf_o.value) == 0


@test()
async def flag_fifo_overflow_is_counted(dut: Any) -> None:
    await _start(dut)
    for w in range(6):  # 6 windows into a 4-deep FIFO with no output: 2 overflows
        await _window_beats(dut, w)
    await ClockCycles(dut.clk_i, 2)
    assert int(dut.flag_ovf_o.value) == 2
