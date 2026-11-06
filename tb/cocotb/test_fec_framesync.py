"""fec_framesync: every window the RTL sends the Viterbi must be the bit-true model's, in order, with its flags.

Why it matters: a wrong frame start or hypothesis decodes a whole frame of garbage, and a missing or extra frame
shifts everything RS and the host see. The model (model/framesync_fixed.py) finds at least the float model's frames
on the bit-true chain (ADR 0010), so matching it frame for frame, counters included, carries that result to the RTL.
Each scenario is one the model's own tests justify (model/tests/test_framesync_fixed.py).
"""

from __future__ import annotations

import numpy as np
from cocotb import test
from framesync_tb import ambiguous_slip, blank_asms, rotate, run_framesync, stream, symbols, write_results

from model.coding import CODED_FRAME_SYMBOLS
from model.framesync_fixed import PRE_SYMBOLS
from model.sync_fixed import ONE

F = CODED_FRAME_SYMBOLS


async def hypothesis(dut, alternate: bool, swap: bool, lead: int = 0) -> None:
    # The derotation comes from these flags; a wrong one decodes garbage. With no lead-in, frame 0 has no run-in and
    # is counted as early; `lead` symbols before it move frame 0 to the boundary.
    u = symbols(np.concatenate([np.zeros(lead, dtype=np.int64), rotate(stream(4, 4, 0.5), alternate, swap)]))
    await run_framesync(dut, f"fs_hyp_{int(alternate)}{int(swap)}_{lead}", u, 0.8, 0.6)


@test()
async def hypothesis_plain(dut) -> None:
    """Frame 0 starts at symbol PRE: its run-in begins exactly at symbol 0, so it is emitted, not early."""
    await hypothesis(dut, False, False, PRE_SYMBOLS)


@test()
async def hypothesis_alternate(dut) -> None:
    """Frame 0 one symbol short of a run-in: early."""
    await hypothesis(dut, True, False, PRE_SYMBOLS - 1)


@test()
async def hypothesis_swap(dut) -> None:
    await hypothesis(dut, False, True)


@test()
async def hypothesis_alternate_swap(dut) -> None:
    await hypothesis(dut, True, True)


@test()
async def flywheel_keeps_a_frame_with_a_missed_asm(dut) -> None:
    """One blanked ASM: the frame is still emitted, flagged in tuser, and lock holds."""
    await run_framesync(dut, "fs_flywheel", symbols(blank_asms(stream(6, 5), range(3, 4), 5)), 0.9, 0.8)


@test()
async def lock_lost_after_flywheel_then_reacquired(dut) -> None:
    """Four blanked ASMs with flywheel 3 (the register, not the default): lock is lost and found again, no frame
    emitted twice."""
    u = symbols(blank_asms(stream(12, 6), range(3, 7), 6))
    await run_framesync(dut, "fs_lose", u, 1.0, 0.9, flywheel=3)


@test()
async def carrier_slip_switches_hypothesis(dut) -> None:
    """90 degree slip: same position, another hypothesis (slip at d = 0)."""
    s = stream(6, 3)
    s[3 * F + 1 :: 2] *= -1
    await run_framesync(dut, "fs_carrier_slip", symbols(s), 0.9, 0.8)


@test()
async def timing_slip_back_overlaps_windows(dut) -> None:
    """A dropped sample: every later ASM one symbol early (d = -1); the windows overlap in the ring."""
    await run_framesync(dut, "fs_slip_m1", symbols(np.delete(stream(6, 3), 2 * F + 5000)), 0.9, 0.8)


@test()
async def timing_slip_forward_two(dut) -> None:
    """Two extra samples: every later ASM two symbols late (d = +2, the edge of the slip window)."""
    s = np.insert(stream(6, 3), 2 * F + 5000, [ONE, -ONE])
    await run_framesync(dut, "fs_slip_p2", symbols(s), 0.9, 0.8)


@test()
async def slip_search_prefers_minus_one_over_plus_one(dut) -> None:
    """ASM-like peaks at e - 1 and e + 1 and none at e: the -1 one is followed, as in the model (nearest first, then
    earlier)."""
    s = ambiguous_slip(stream(5, 3), 2 * F + 12, 1, 2)
    await run_framesync(dut, "fs_slip_tie", symbols(s), 0.9, 0.8)


@test()
async def noise_then_frames(dut) -> None:
    """40,000 symbols of noise lock on nothing; the frames after it are found (none early: past the run-in)."""
    rng = np.random.default_rng(9)
    noise = np.round(ONE * rng.standard_normal(40_000)).astype(np.int64)
    await run_framesync(dut, "fs_noise", symbols(np.concatenate([noise, stream(4, 8, 0.5)])), 0.9, 0.8)


@test()
async def low_threshold_fills_the_queue(dut) -> None:
    """thr 16/64 on noise: thousands of false peaks fill the verify queue (dropped, counted), most fail verify, and
    lock still lands where the model's does, slips included."""
    rng = np.random.default_rng(9)
    noise = np.round(ONE * rng.standard_normal(20_000)).astype(np.int64)
    await run_framesync(dut, "fs_queue", symbols(np.concatenate([noise, stream(4, 8, 0.5)])), 0.9, 0.8, thr64=16)


@test()
async def slow_viterbi_stalls_the_input_not_the_ring(dut) -> None:
    """A sink that stops: the input must stall once the ring is full (not overwrite a pending window), and resume."""
    out = await run_framesync(dut, "fs_ring_stall", symbols(stream(5, 4, 0.5)), 1.0, 0.8, hold_sink_until_stall=500)
    assert out.stalled_clocks >= 500
    write_results()  # the last scenario: every row is in
