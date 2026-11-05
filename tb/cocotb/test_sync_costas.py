"""sync_costas: fourth-order Costas loop, bit-exact against model/sync_fixed.py costas().

Why it matters: the Costas loop removes the residual carrier and tracks Doppler; without it the constellation is a
spinning ring and nothing downstream decodes. It is a per-sample feedback loop, so a phase update applied one sample
late, a frequency integrator that wraps instead of clamping, or a phase detector with the wrong sign at zero still
produces plausible output but a different trajectory. Every output is compared with the model, and the input is
chosen so the loop really pulls in: the residual left after the host's coarse estimate (ADR 0002), with the AGC
settled. The model's frequency track, which the RTL then matches implicitly, must reach the residual.
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
RESIDUAL_HZ = 50.0  # after the coarse estimate; pulls in by ~5,000 samples (100 Hz does not within 16,000)
ROWS: list[list[object]] = []  # filled by each test; written by the last one when WRITE_RESULTS=1


def agc_output(n_cu8: int, seed: int) -> tuple[np.ndarray, np.ndarray, RxConfig]:
    """Bit-true AGC output (gain pre-settled) of 6 dB OQPSK with a RESIDUAL_HZ carrier and a 30 Hz/s ramp."""
    tx = TxConfig()
    _, on_air = build_cadus(1, seed)
    sigma = noise_sigma(6.0, tx.fs)
    x = awgn(apply_carrier(modulate(encode_stream(on_air), tx), tx.fs, CARRIER_HZ, 30.0, 0.7), sigma, seed)[:n_cu8]
    cfg = RxConfig(fs=tx.fs, tune_offset_hz=CARRIER_HZ - RESIDUAL_HZ)
    i, q = rrc_fixed.rrc_fixed(*ddc_fixed.ddc_fixed_rails(to_cu8(x, full_scale=4 * sigma), cfg), cfg)
    _, _, gains = sync_fixed.agc(i, q)
    i, q, _ = sync_fixed.agc(i, q, int(gains[-1]))
    return i, q, cfg


async def run(dut, i, q, gains: sync_fixed.LoopGains, name: str, p_valid: float, p_ready: float):
    ei, eq, track = sync_fixed.costas(i, q, gains)
    expected = list(zip(ei.tolist(), eq.tolist(), strict=True))

    def setup(dut) -> None:
        dut.kp_i.value = gains.costas_kp
        dut.ki_i.value = gains.costas_ki
        dut.fmax_i.value = gains.costas_max

    got = await run_stream(dut, name, pack_iq(i, q, W), expected, lambda d: unpack_iq(d, W), p_valid, p_ready, setup)
    return got, track


@test()
async def pulls_in_residual_backpressure(dut) -> None:
    """16,000 samples, random stalls on both sides; the loop must lock to the residual inside the run."""
    i, q, cfg = agc_output(64_000, 16)
    got, track = await run(dut, i, q, sync_fixed.loop_gains(cfg), "costas_lock", 0.7, 0.6)
    hz = sync_fixed.freq_hz(track, cfg)
    end = float(np.mean(hz[-2000:]))
    assert abs(end - RESIDUAL_HZ) < 20, f"loop ended at {end:.1f} Hz, not locked to the {RESIDUAL_HZ:.0f} Hz residual"
    ROWS.append(["bit_exact_lock_backpressure", i.size, len(got), 0, f"{end:.1f}", "", "", ""])


@test()
async def frequency_clamps(dut) -> None:
    """fmax set to 20 Hz below the 50 Hz residual: the integrator must sit at the clamp, not wrap or overshoot."""
    i, q, cfg = agc_output(32_000, 17)
    base = sync_fixed.loop_gains(cfg)
    fmax = round(20.0 / (cfg.fs / cfg.decimation) * sync_fixed.TWO_PI * (1 << sync_fixed.FREQ_FRAC))
    got, track = await run(dut, i, q, dataclasses.replace(base, costas_max=fmax), "costas_clamp", 0.9, 0.9)
    assert track.max() == fmax, "the frequency integrator never reached its clamp"
    ROWS.append(["bit_exact_clamp", i.size, len(got), 0, "", "", "", ""])


@test()
async def throughput_leaves_real_time_margin(dut) -> None:
    """With the output always ready, the loop must keep up with 256 kS/s with at least 4x headroom."""
    i, q, cfg = agc_output(8_000, 18)
    n = i.size
    t0 = get_sim_time("ns")
    await run(dut, i, q, sync_fixed.loop_gains(cfg), "costas_rate", 1.0, 1.0)
    cycles_per_sample = (get_sim_time("ns") - t0) / 10 / n
    budget = CLK_HZ / (cfg.fs / cfg.decimation)
    dut._log.info("throughput: %.2f cycles per sample; budget %.1f at 100 MHz (%.1fx headroom)",
                  cycles_per_sample, budget, budget / cycles_per_sample)
    ROWS.append(["throughput_no_stall", n, n, 0, "", f"{cycles_per_sample:.2f}", f"{budget:.1f}",
                 f"{budget / cycles_per_sample:.1f}"])
    if os.environ.get("WRITE_RESULTS") == "1":
        from analysis.common import write_result

        verilator = subprocess.run(["verilator", "--version"], capture_output=True, text=True).stdout.split()[1]
        write_result(
            "costas_rtl_sim",
            ["test", "samples_in", "outputs_checked", "mismatches", "final_freq_hz", "cycles_per_sample",
             "budget_cycles_100mhz", "headroom"],
            ROWS,
            "seeds 16-18 in tb/cocotb/test_sync_costas.py (bit-true AGC output of OQPSK at 6 dB Eb/N0, 50 Hz "
            "residual carrier after the coarse estimate, 30 Hz/s ramp; 20 Hz clamp for the clamp test)",
            command="make sync-rtl-results",
            tools=f"Verilator {verilator}, cocotb {cocotb.__version__}",
        )
    assert cycles_per_sample < budget / 4, "less than 4x real-time headroom at a 100 MHz core clock"
