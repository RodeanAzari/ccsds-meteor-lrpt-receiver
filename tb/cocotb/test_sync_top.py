"""sync_top: RRC -> AGC -> Costas -> timing as one chain, bit-exact against the model chain in model/sync_fixed.py.

Why it matters: each sync block matches the model alone, but the chain also depends on the handshakes between them.
Three of the four blocks hold one sample in flight and accept input only with their output empty, so a stage that
drops or repeats a beat when its neighbour stalls passes its own test and still corrupts the stream here. The input
is what the receiver will see after the host's coarse estimate and the DDC (sync_chain.py). The AGC starts from gain
1.0 as after reset, not pre-settled, so the loops start cold as they will on the board. The end-to-end decode of the
chain's output is in test_sync_top_full.py (make sim-full); it needs ~60,000 samples, too long for make sim.
"""

from __future__ import annotations

import os
import subprocess

import cocotb
from cocotb import test
from cocotb.utils import get_sim_time
from stream_tb import pack_iq, run_stream, unpack_iq
from sync_chain import ddc_input, expected, set_gains

W = 16
CLK_HZ = 100e6  # planned core clock (CLAUDE.md §3.3)
ROWS: list[list[object]] = []  # filled by each test; written by the last one when WRITE_RESULTS=1


async def run(dut, n: int, seed: int, name: str, p_valid: float, p_ready: float) -> tuple[int, int]:
    i, q, cfg, _ = ddc_input(1, seed)
    i, q = i[:n], q[:n]
    re, im = expected(i, q, cfg)
    got = await run_stream(dut, name, pack_iq(i, q, W), list(zip(re.tolist(), im.tolist(), strict=True)),
                           lambda d: unpack_iq(d, W), p_valid, p_ready, lambda d: set_gains(d, cfg))
    return n, len(got)


@test()
async def chain_bit_exact_backpressure(dut) -> None:
    """12,000 DDC samples with random input gaps and an output slower than the chain, so stalls reach every stage.

    The chain makes ~0.56 outputs per 62-clock RRC sample. With the sink ready half the time, every stage drains in a
    few clocks and no stall ever reaches the AGC -> Costas link: a planted AGC that ignored Costas's tready passed.
    Ready 0.8% of the time (0.5 per 62 clocks) keeps the output the bottleneck, and that mutant fails.
    """
    n, outs = await run(dut, 12_000, 30, "sync_top", 0.8, 0.008)
    ROWS.append(["bit_exact_backpressure", n, outs, 0, "", "", ""])


@test()
async def throughput_leaves_real_time_margin(dut) -> None:
    """With the output always ready, the chain must keep up with 256 kS/s in with at least 4x headroom."""
    t0 = get_sim_time("ns")
    n, outs = await run(dut, 3000, 31, "sync_top_rate", 1.0, 1.0)
    cycles_per_sample = (get_sim_time("ns") - t0) / 10 / n
    budget = CLK_HZ / 256e3
    dut._log.info("throughput: %.2f cycles per input sample; budget %.1f at 100 MHz (%.1fx headroom)",
                  cycles_per_sample, budget, budget / cycles_per_sample)
    ROWS.append(["throughput_no_stall", n, outs, 0, f"{cycles_per_sample:.2f}", f"{budget:.1f}",
                 f"{budget / cycles_per_sample:.1f}"])
    if os.environ.get("WRITE_RESULTS") == "1":
        from analysis.common import write_result

        verilator = subprocess.run(["verilator", "--version"], capture_output=True, text=True).stdout.split()[1]
        write_result(
            "sync_top_rtl_sim",
            ["test", "samples_in", "outputs_checked", "mismatches", "cycles_per_sample", "budget_cycles_100mhz",
             "headroom"],
            ROWS,
            "seeds 30-31 in tb/cocotb/test_sync_top.py via sync_chain.py (bit-true DDC output of OQPSK at 6 dB "
            "Eb/N0, 1 kHz offset + 30 Hz/s before the coarse estimate, 0.37 symbol timing offset, 20 ppm clock; "
            "AGC from gain 1.0)",
            command="make sync-rtl-results",
            tools=f"Verilator {verilator}, cocotb {cocotb.__version__}",
        )
    assert cycles_per_sample < budget / 4, "less than 4x real-time headroom at a 100 MHz core clock"
