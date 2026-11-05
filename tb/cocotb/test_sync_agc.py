"""sync_agc: feedback AGC on I^2 + Q^2, bit-exact against model/sync_fixed.py agc().

Why it matters: the AGC sets the scale everything downstream assumes. Costas and Gardner loop gains are computed for
rail rms ONE, and the 4-bit soft quantizer's step is ONE/4; an AGC that settles at the wrong level changes the loop
bandwidths and wastes soft-decision levels. Because the loop is per sample, a gain update applied one sample late
(an easy pipeline mistake) still settles and looks plausible, but the output no longer matches the model, so every
test compares every output. Strong input after silence drives the output into saturation.
"""

from __future__ import annotations

import os
import subprocess

import cocotb
import numpy as np
from cocotb import test
from cocotb.utils import get_sim_time
from stream_tb import pack_iq, run_stream, unpack_iq

from model import ddc_fixed, rrc_fixed, sync_fixed
from model.channel import TxConfig, apply_carrier, awgn, modulate, noise_sigma, to_cu8
from model.coding import build_cadus, encode_stream
from model.receiver import RxConfig

W = 16
CLK_HZ = 100e6  # planned core clock (CLAUDE.md §3.3)
ROWS: list[list[object]] = []  # filled by each test; written by the last one when WRITE_RESULTS=1


async def run(dut, i: np.ndarray, q: np.ndarray, name: str, p_valid: float, p_ready: float):
    ei, eq, gains = sync_fixed.agc(i, q)
    expected = list(zip(ei.tolist(), eq.tolist(), strict=True))
    got = await run_stream(dut, name, pack_iq(i, q, W), expected, lambda d: unpack_iq(d, W), p_valid, p_ready)
    return got, gains


def rrc_output(n_cu8: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Bit-true RRC output of OQPSK frames at 6 dB Eb/N0, 151 kHz off with a 30 Hz/s ramp: what the AGC sees."""
    tx = TxConfig()
    _, on_air = build_cadus(1, seed)
    sigma = noise_sigma(6.0, tx.fs)
    x = awgn(apply_carrier(modulate(encode_stream(on_air), tx), tx.fs, 151_000.0, 30.0, 0.7), sigma, seed)[:n_cu8]
    cfg = RxConfig(fs=tx.fs, tune_offset_hz=150_000.0)
    return rrc_fixed.rrc_fixed(*ddc_fixed.ddc_fixed_rails(to_cu8(x, full_scale=4 * sigma), cfg), cfg)


@test()
async def modulated_signal_backpressure(dut) -> None:
    """Real-level input from gain 1.0: the gain climbs every sample, so a late update would show at once."""
    i, q = rrc_output(48_000, 13)
    got, gains = await run(dut, i, q, "agc_modulated", 0.7, 0.6)
    assert gains[-1] > gains[0], "gain never rose on a weak input"
    ROWS.append(["bit_exact_backpressure", i.size, len(got), 0, "", "", ""])


@test()
async def strong_input_saturates(dut) -> None:
    """Silence lets the gain climb above 1.0; a full-scale burst then overflows s16, so the output must clip (not
    wrap). The loop must then pull the output rms back into its dead zone around ONE: the update
    round((2*ONE^2 - p) >> 24) is zero for p within +-2^23 of 2*ONE^2, i.e. rail rms 0.87-1.12 ONE. On a
    constant-envelope input the gain stops anywhere in it (572 here, not the ideal 512); noise dithers it to unit
    power on real signals (data/results/sync_fixed_chain.csv).

    The gain's lower clamp (1) is unreachable from s16 input: a saturated output moves the gain by at most -128 per
    sample, and the loop settles at 512. The upper clamp needs ~2^19 silent samples; both are checked in the model."""
    rng = np.random.default_rng(14)
    quiet, loud = 1500, 1000
    burst_i = np.where(rng.random(loud) < 0.5, 32767, -32768)
    burst_q = np.where(rng.random(loud) < 0.5, 32767, -32768)
    i = np.concatenate([np.zeros(quiet), burst_i]).astype(np.int64)
    q = np.concatenate([np.zeros(quiet), burst_q]).astype(np.int64)
    got, gains = await run(dut, i, q, "agc_strong", 0.8, 0.8)
    unclipped = (i * gains + (1 << (sync_fixed.AGC_FRAC - 1))) >> sync_fixed.AGC_FRAC
    assert (np.abs(unclipped) > 32768).any(), "the burst never overflowed s16, so saturation went untested"
    settled = np.array(got[-200:], dtype=np.float64)
    rms = float(np.sqrt(np.mean(settled**2)))
    lo, hi = np.sqrt(0.75) * sync_fixed.ONE, np.sqrt(1.25) * sync_fixed.ONE
    assert lo < rms <= hi, f"output rail rms {rms:.0f} outside the AGC dead zone ({lo:.0f}, {hi:.0f}]"
    ROWS.append(["saturation", i.size, len(got), 0, "", "", ""])


@test()
async def throughput_leaves_real_time_margin(dut) -> None:
    """With the output always ready, the AGC must keep up with 256 kS/s with at least 4x headroom."""
    cfg = RxConfig()
    i, q = rrc_output(8_000, 15)
    n = i.size
    t0 = get_sim_time("ns")
    await run(dut, i, q, "agc_rate", 1.0, 1.0)
    cycles_per_sample = (get_sim_time("ns") - t0) / 10 / n
    budget = CLK_HZ / (cfg.fs / cfg.decimation)
    dut._log.info("throughput: %.2f cycles per sample; budget %.1f at 100 MHz (%.1fx headroom)",
                  cycles_per_sample, budget, budget / cycles_per_sample)
    ROWS.append(["throughput_no_stall", n, n, 0, f"{cycles_per_sample:.2f}", f"{budget:.1f}",
                 f"{budget / cycles_per_sample:.1f}"])
    if os.environ.get("WRITE_RESULTS") == "1":
        from analysis.common import write_result

        verilator = subprocess.run(["verilator", "--version"], capture_output=True, text=True).stdout.split()[1]
        write_result(
            "agc_rtl_sim",
            ["test", "samples_in", "outputs_checked", "mismatches", "cycles_per_sample", "budget_cycles_100mhz",
             "headroom"],
            ROWS,
            "seeds 13-15 in tb/cocotb/test_sync_agc.py (bit-true RRC output of OQPSK at 6 dB Eb/N0, 151 kHz carrier, "
            "30 Hz/s ramp; random full-scale for saturation)",
            command="make sync-rtl-results",
            tools=f"Verilator {verilator}, cocotb {cocotb.__version__}",
        )
    assert cycles_per_sample < budget / 4, "less than 4x real-time headroom at a 100 MHz core clock"
