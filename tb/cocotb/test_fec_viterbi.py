"""fec_viterbi: quantized soft symbols in, decoded bits out, bit-exact against model/viterbi_fixed.viterbi_fixed().

Why it matters: the ACS array and the traceback each match the model alone; together they also depend on the
64-bit decision handshake between them. The traceback stalls the array for ~100 clocks per bit, so a link that
dropped or repeated a row under that stall would pass both block tests and still shift every later bit. The low-SNR
run also checks that the RTL's errors are exactly the model's, not just as many: the BER that the hardware campaign
will measure is then the model's curve (buildplan §9 Phase D).
"""

from __future__ import annotations

import os
import subprocess

import cocotb
import numpy as np
from cocotb import test
from cocotb.utils import get_sim_time
from fec_vectors import SOFT_BITS, coded_symbols, pairs
from stream_tb import run_stream

from model.viterbi_fixed import TRACEBACK_DEPTH, path_metric_bits, viterbi_fixed

CLK_HZ = 100e6  # planned core clock (CLAUDE.md §3.3)
BIT_RATE = 72_000.0  # decoded bits/s: 72 ksym/s OQPSK carries 144 k coded bits/s at r = 1/2 (signal-spec.md)
ROWS: list[list[object]] = []  # filled by each test; written by the last one when WRITE_RESULTS=1


async def run(dut, n_bits: int, ebn0_db: float, seed: int, name: str, p_valid: float, p_ready: float) -> float:
    sent, u = coded_symbols(n_bits, ebn0_db, seed)
    bits, _ = viterbi_fixed(u, SOFT_BITS, path_metric_bits(SOFT_BITS), TRACEBACK_DEPTH, "zero")
    want = bits[: n_bits - TRACEBACK_DEPTH]  # the model's last depth bits come from a block-end traceback
    t0 = get_sim_time("ns")
    got = await run_stream(dut, name, pairs(u), want.tolist(), int, p_valid, p_ready,
                           lambda d: setattr(d.depth_i, "value", TRACEBACK_DEPTH), drain_cycles=1000)
    clocks = (get_sim_time("ns") - t0) / 10 / n_bits
    errors = int(np.count_nonzero(np.array(got) != sent[: len(got)]))
    dut._log.info("%.1f dB: %d bits bit-exact against the model; %d bit errors vs. sent; %.1f clocks per bit",
                  ebn0_db, len(got), errors, clocks)
    ROWS.append([name, ebn0_db, n_bits, len(got), 0, errors, f"{clocks:.1f}", f"{CLK_HZ / BIT_RATE:.0f}",
                 f"{CLK_HZ / BIT_RATE / clocks:.1f}"])
    return clocks


@test()
async def low_snr_backpressure(dut) -> None:
    """1.5 dB, where the decoder makes errors: the RTL must make exactly the model's."""
    await run(dut, 4000, 1.5, 61, "fec_viterbi", 0.7, 0.6)


@test()
async def throughput_leaves_real_time_margin(dut) -> None:
    """No stalls: the traceback sets the rate, depth + ~4 clocks per bit, against 1,389 at 100 MHz."""
    clocks = await run(dut, 3000, 4.0, 62, "fec_viterbi_rate", 1.0, 1.0)
    if os.environ.get("WRITE_RESULTS") == "1":
        from analysis.common import write_result

        verilator = subprocess.run(["verilator", "--version"], capture_output=True, text=True).stdout.split()[1]
        write_result(
            "viterbi_rtl_sim",
            ["test", "ebn0_db", "bits_in", "bits_checked", "mismatches", "bit_errors_vs_sent", "clocks_per_bit",
             "budget_clocks_100mhz", "headroom"],
            ROWS,
            "seeds 61-62 in tb/cocotb/test_fec_viterbi.py via fec_vectors.py (random bits, K=7 r=1/2, antipodal "
            "at rail rms ONE + AWGN, 4-bit quantized); traceback depth 96 from state 0",
            command="make fec-rtl-results",
            tools=f"Verilator {verilator}, cocotb {cocotb.__version__}",
        )
    assert clocks < CLK_HZ / BIT_RATE / 4, "less than 4x real-time headroom at a 100 MHz core clock"
