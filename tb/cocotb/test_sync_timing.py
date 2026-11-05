"""sync_timing: Farrow resampler + per-rail OQPSK Gardner, bit-exact against model/sync_fixed.py timing().

Why it matters: the timing loop picks the instants the soft symbols are taken at. Strobes half a symbol off land on
the transitions, and the Viterbi sees noise. The loop is a per-output feedback loop, so a position updated with the
previous output's error, the detector run on the wrong rail for odd outputs, an integrator that wraps instead of
clamping, or a Horner step rounded differently produces plausible samples on a different trajectory. Every output is
compared with the model. The lock input starts half a symbol off, so the loop must pull in, and the
test checks that it does: the strobe eye ratio (mean |soft| / std |soft|) at the end of the run must clear a no-loop
baseline that the model shows stays closed.
"""

from __future__ import annotations

import dataclasses
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
CARRIER_HZ = 151_000.0
OFFSET_SYM = 0.5  # worst case: every strobe on a transition
CLOCK_PPM = 100.0  # clamp test only: over a run it drifts the offset by 0.45 symbol, which would align a dead loop
EYE_LOCKED = 1.9  # model, seed 16: 2.07 with the loop, 1.46 without (scratch study 2026-11-05)
ROWS: list[list[object]] = []  # filled by each test; written by the last one when WRITE_RESULTS=1


def costas_output(n_cu8: int, seed: int, ppm: float = 0.0) -> tuple[np.ndarray, np.ndarray, RxConfig]:
    """Bit-true Costas output of 6 dB OQPSK, OFFSET_SYM late with a `ppm` clock error, carrier centred."""
    tx = TxConfig(timing_offset_sym=OFFSET_SYM, clock_ppm=ppm)
    _, on_air = build_cadus(1, seed)
    sigma = noise_sigma(6.0, tx.fs)
    x = awgn(apply_carrier(modulate(encode_stream(on_air), tx), tx.fs, CARRIER_HZ, 0.0, 0.7), sigma, seed)[:n_cu8]
    cfg = RxConfig(fs=tx.fs, tune_offset_hz=CARRIER_HZ)
    i, q = rrc_fixed.rrc_fixed(*ddc_fixed.ddc_fixed_rails(to_cu8(x, full_scale=4 * sigma), cfg), cfg)
    _, _, agc_gain = sync_fixed.agc(i, q)
    i, q, _ = sync_fixed.agc(i, q, int(agc_gain[-1]))
    i, q, _ = sync_fixed.costas(i, q, sync_fixed.loop_gains(cfg))
    return i, q, cfg


def eye(re: np.ndarray, im: np.ndarray) -> float:
    """Mean over std of |soft| at the strobes: high when the strobes sit on the symbols."""
    m = np.abs(sync_fixed.serial(re, im)).astype(float)
    return float(m.mean() / m.std())


async def run(dut, i, q, gains: sync_fixed.LoopGains, name: str, p_valid: float, p_ready: float):
    # The model stops one sample before the stream does; with one sample more it gives exactly what the RTL emits.
    ere, eim = sync_fixed.timing(np.append(i, 0), np.append(q, 0), gains)
    expected = list(zip(ere.tolist(), eim.tolist(), strict=True))

    def setup(dut) -> None:
        dut.nominal_i.value = gains.timing_nominal
        dut.kp_i.value = gains.timing_kp
        dut.ki_i.value = gains.timing_ki
        dut.limit_i.value = gains.timing_limit

    got = await run_stream(dut, name, pack_iq(i, q, W), expected, lambda d: unpack_iq(d, W), p_valid, p_ready, setup)
    return got, ere, eim


@test()
async def pulls_in_half_symbol_backpressure(dut) -> None:
    """16,000 samples, random stalls on both sides; the strobes must move onto the symbols inside the run."""
    i, q, cfg = costas_output(64_000, 16)
    gains = sync_fixed.loop_gains(cfg)
    got, re, im = await run(dut, i, q, gains, "timing_lock", 0.7, 0.6)
    end = eye(re[-2000:], im[-2000:])
    off_re, off_im = sync_fixed.timing(i, q, dataclasses.replace(gains, timing_kp=0, timing_ki=0))
    baseline = eye(off_re[-2000:], off_im[-2000:])
    assert baseline < EYE_LOCKED, f"no-loop baseline {baseline:.2f} already clears {EYE_LOCKED}: the check is void"
    assert end > EYE_LOCKED, f"eye ratio {end:.2f} at the end (no loop: {baseline:.2f}): the loop did not pull in"
    ROWS.append(["bit_exact_lock_backpressure", i.size, len(got), 0, f"{end:.2f}", f"{baseline:.2f}", "", "", ""])


@test()
async def integrator_clamps(dut) -> None:
    """Limit set to one ki step: almost every update saturates the integrator, which must clamp, not wrap."""
    i, q, cfg = costas_output(32_000, 17, CLOCK_PPM)
    base = sync_fixed.loop_gains(cfg)
    got, _, _ = await run(dut, i, q, dataclasses.replace(base, timing_limit=base.timing_ki), "timing_clamp", 0.9, 0.9)
    ROWS.append(["bit_exact_clamp", i.size, len(got), 0, "", "", "", "", ""])


@test()
async def throughput_leaves_real_time_margin(dut) -> None:
    """With the output always ready, the block must keep up with 256 kS/s in with at least 4x headroom."""
    i, q, cfg = costas_output(8_000, 18)
    n = i.size
    t0 = get_sim_time("ns")
    got, _, _ = await run(dut, i, q, sync_fixed.loop_gains(cfg), "timing_rate", 1.0, 1.0)
    cycles_per_sample = (get_sim_time("ns") - t0) / 10 / n
    budget = CLK_HZ / (cfg.fs / cfg.decimation)
    dut._log.info("throughput: %.2f cycles per input sample; budget %.1f at 100 MHz (%.1fx headroom)",
                  cycles_per_sample, budget, budget / cycles_per_sample)
    ROWS.append(["throughput_no_stall", n, len(got), 0, "", "", f"{cycles_per_sample:.2f}", f"{budget:.1f}",
                 f"{budget / cycles_per_sample:.1f}"])
    if os.environ.get("WRITE_RESULTS") == "1":
        from analysis.common import write_result

        verilator = subprocess.run(["verilator", "--version"], capture_output=True, text=True).stdout.split()[1]
        write_result(
            "timing_rtl_sim",
            ["test", "samples_in", "outputs_checked", "mismatches", "eye_end", "eye_no_loop", "cycles_per_sample",
             "budget_cycles_100mhz", "headroom"],
            ROWS,
            "seeds 16-18 in tb/cocotb/test_sync_timing.py (bit-true Costas output of OQPSK at 6 dB Eb/N0, 0.5 symbol "
            "timing offset, carrier centred; clamp test: 100 ppm clock error and limit = one ki step)",
            command="make sync-rtl-results",
            tools=f"Verilator {verilator}, cocotb {cocotb.__version__}",
        )
    assert cycles_per_sample < budget / 4, "less than 4x real-time headroom at a 100 MHz core clock"
