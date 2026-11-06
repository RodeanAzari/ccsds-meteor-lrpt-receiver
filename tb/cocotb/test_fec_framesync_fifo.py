"""fec_framesync with a 128k-symbol ring: the descriptor FIFO, not the ring, is what stops the input.

Why it matters: the FSM emits up to two frames on one symbol, so the input must stall while fewer than two FIFO
entries are free. With the default 32k ring the ring always stalls first (a 64k ring too, at 4 descriptors), so only a
ring holding more than the FIFO's 4 frames reaches this path. Without the check the FIFO overflows (a_fifo_no_overflow)
or loses a window.
"""

from __future__ import annotations

from cocotb import test
from framesync_tb import run_framesync, stream, symbols


@test()
async def full_descriptor_fifo_stalls_the_input(dut) -> None:
    out = await run_framesync(dut, "fs_fifo_stall", symbols(stream(7, 4, 0.5)), 1.0, 0.8, hold_sink_until_stall=500)
    assert out.stalled_clocks >= 500
