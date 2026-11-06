"""Frame sync harness: stream 4-bit symbols into fec_framesync, check every window against the bit-true model.

Expected output: model/framesync_fixed.py frame_sync_fixed() then windows(), on the same symbols: each window's pairs,
its tuser {flywheel, swap, alternate} on every beat, tlast only on its last pair; then the status counters.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import cocotb
import numpy as np
from cocotb import start_soon
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge
from tb_common import get_rng
from tb_common.axis import AxisBeat, AxisSink, AxisSource

from model.framesync_fixed import frame_sync_fixed, windows
from model.tests.framesync_stimulus import ambiguous_slip, blank_asms, rotate, stream, symbols

__all__ = ["ambiguous_slip", "blank_asms", "rotate", "run_framesync", "stream", "symbols", "write_results"]

ROWS: list[list[object]] = []  # one per scenario; written by write_results() under make fec-rtl-results
THR64 = 48  # RxConfig.sync_threshold * 64
FLYWHEEL = 4  # RxConfig.flywheel


@dataclass
class Outcome:
    windows: int
    stalled_clocks: int  # clocks with s_tvalid high and s_tready low


async def run_framesync(
    dut: Any,
    name: str,
    u: np.ndarray,
    p_valid: float,
    p_ready: float,
    thr64: int = THR64,
    flywheel: int = FLYWHEEL,
    hold_sink_until_stall: int = 0,
) -> Outcome:
    """Reset, stream u, check windows and counters against the model. With hold_sink_until_stall = n, the sink holds
    tready low until the input has been refused for n consecutive clocks, then runs at p_ready."""
    res = frame_sync_fixed(u, thr64, flywheel)
    want, early = windows(u, res)
    assert want, "scenario produces no window: it would test nothing"

    start_soon(Clock(dut.clk_i, 10, unit="ns").start())
    rng = get_rng(name)
    dut.rst_i.value = 1
    dut.s_tvalid_i.value = 0
    dut.thr64_i.value = thr64
    dut.flywheel_i.value = flywheel
    await ClockCycles(dut.clk_i, 3)
    dut.rst_i.value = 0

    got: list[list[AxisBeat]] = []

    def on_frame(frame: list[AxisBeat]) -> None:
        k = len(got)
        assert k < len(want), f"{name}: window {k} beyond the model's {len(want)}"
        w = want[k]
        data = np.array([b.data for b in frame], dtype=np.int64)
        assert data.size == w.pairs.size, f"{name}: window {k} has {data.size} pairs, model {w.pairs.size}"
        bad = np.flatnonzero(data != w.pairs)
        assert bad.size == 0, f"{name}: window {k} differs at pair {bad[0]} of {data.size} ({bad.size} pairs)"
        user = (int(w.flywheel) << 2) | (int(w.swap) << 1) | int(w.alternate)
        users = {b.user for b in frame}
        assert users == {user}, f"{name}: window {k} tuser {users}, model {user}"
        got.append(frame)

    sink = AxisSink(dut, dut.clk_i, "m_", rng=rng, p_ready=0.0 if hold_sink_until_stall else p_ready,
                    callback=on_frame)
    stalled = 0

    async def watch_stall() -> None:
        nonlocal stalled
        run = 0
        while True:
            await RisingEdge(dut.clk_i)
            refused = bool(dut.s_tvalid_i.value) and not bool(dut.s_tready_o.value)
            stalled += refused
            run = run + 1 if refused else 0
            if hold_sink_until_stall and run == hold_sink_until_stall:
                sink.p_ready = p_ready

    start_soon(watch_stall())
    src = AxisSource(dut, dut.clk_i, "s_", rng=rng, p_valid=p_valid)
    await src.send(AxisBeat(int(x)) for x in u)
    # Each pair takes ~4 clocks at the reader plus the sink's pace.
    budget = int(len(want) * want[0].pairs.size * (5 / max(p_ready, 0.05))) + 1000
    for _ in range(budget):
        if len(got) == len(want):
            break
        await RisingEdge(dut.clk_i)
    assert len(got) == len(want), f"{name}: {len(got)} windows out, model {len(want)}"
    await ClockCycles(dut.clk_i, 200)  # nothing more may follow
    assert len(got) == len(want)
    counters: list[tuple[str, int, Callable[[], int]]] = [
        ("early", early, lambda: int(dut.early_o.value)),
        ("dropped", res.dropped, lambda: int(dut.dropped_o.value)),
        ("slips", res.slips, lambda: int(dut.slips_o.value)),
    ]
    for label, model_value, read in counters:
        assert read() == model_value, f"{name}: {label} = {read()}, model {model_value}"
    ROWS.append([name, u.size, thr64, flywheel, len(got), sum(w.pairs.size for w in want), 0,
                 sum(w.flywheel for w in want), early, res.dropped, res.slips, stalled])
    dut._log.info("%s: %d windows bit-exact (%d flywheel), early %d, dropped %d, slips %d, input stalled %d clocks",
                  name, len(got), sum(w.flywheel for w in want), early, res.dropped, res.slips, stalled)
    return Outcome(len(got), stalled)


def write_results() -> None:
    """data/results/framesync_rtl_sim.csv, when WRITE_RESULTS=1 (make fec-rtl-results)."""
    if os.environ.get("WRITE_RESULTS") != "1":
        return
    from analysis.common import write_result

    verilator = subprocess.run(["verilator", "--version"], capture_output=True, text=True).stdout.split()[1]
    write_result(
        "framesync_rtl_sim",
        ["scenario", "symbols_in", "thr64", "flywheel", "windows", "pairs_checked", "mismatches", "flywheel_windows",
         "early", "dropped", "slips", "input_stalled_clocks"],
        ROWS,
        "coded frames from model/tests/framesync_stimulus.py (build_cadus seeds 3-8, antipodal at rail rms "
        "ONE + AWGN where noted, 4-bit quantized), per scenario in tb/cocotb/test_fec_framesync.py",
        command="make fec-rtl-results",
        tools=f"Verilator {verilator}, cocotb {cocotb.__version__}",
    )
