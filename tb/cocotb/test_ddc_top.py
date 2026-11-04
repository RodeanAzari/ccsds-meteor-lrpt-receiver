"""ddc_top: the whole DDC on a modulated signal, bit-exact against model/ddc_fixed.py ddc_fixed_rails().

Why it matters: each block matches the model alone, but the chain also depends on the handshakes between them. A
stage that drops or repeats a beat when its neighbour stalls passes its own test and still corrupts the stream here.
The input is what the receiver will see: OQPSK frames on a carrier 151 kHz off, a 30 Hz/s Doppler ramp, noise and
a DC offset, quantized to cu8. The throughput check makes sure the time-shared FIR leaves real-time margin.
"""

from __future__ import annotations

import os
import subprocess

import cocotb
import numpy as np
from cocotb import test
from cocotb.utils import get_sim_time
from stream_tb import run_stream, unpack_iq

from model import ddc_fixed as m
from model.channel import TxConfig, apply_carrier, awgn, modulate, noise_sigma, to_cu8
from model.coding import build_cadus, encode_stream
from model.receiver import RxConfig

N_SAMPLES = 24_000  # 1.7k symbols; long enough for every pipeline to fill and the DC block to settle
CLK_HZ = 100e6  # planned core clock (CLAUDE.md §3.3)
ROWS: list[list[object]] = []  # filled by each test; written by the last one when WRITE_RESULTS=1


def signal(seed: int) -> tuple[np.ndarray, RxConfig]:
    tx = TxConfig()
    _, on_air = build_cadus(1, seed)
    sigma = noise_sigma(6.0, tx.fs)
    x = awgn(apply_carrier(modulate(encode_stream(on_air), tx), tx.fs, 151_000.0, 30.0, 0.7), sigma, seed)
    x = x[:N_SAMPLES] + 0.3 * sigma * (1 + 1j)  # an RTL-SDR-like DC offset for the DC block to remove
    return to_cu8(x, full_scale=4 * sigma), RxConfig(fs=tx.fs, tune_offset_hz=150_000.0)


@test()
async def modulated_signal_backpressure(dut) -> None:
    raw, cfg = signal(8)
    i, q = m.ddc_fixed_rails(raw, cfg)
    expected = list(zip(i.tolist(), q.tolist(), strict=True))
    words = (raw[0::2].astype(int) | (raw[1::2].astype(int) << 8)).tolist()

    def setup(dut) -> None:
        dut.freq_word_i.value = m.freq_word(cfg.tune_offset_hz, cfg.fs)

    got = await run_stream(dut, "ddc_top", words, expected, lambda d: unpack_iq(d, 16), 0.9, 0.5, setup)
    ROWS.append(["bit_exact_backpressure", N_SAMPLES, len(got), 0, "", "", ""])


@test()
async def throughput_leaves_real_time_margin(dut) -> None:
    """With the output always ready, the DDC must take a 1.024 MS/s stream in well under 1/1.024e6 s per sample."""
    raw, cfg = signal(9)
    n = 4000
    raw = raw[: 2 * n]
    i, q = m.ddc_fixed_rails(raw, cfg)
    words = (raw[0::2].astype(int) | (raw[1::2].astype(int) << 8)).tolist()

    def setup(dut) -> None:
        dut.freq_word_i.value = m.freq_word(cfg.tune_offset_hz, cfg.fs)

    t0 = get_sim_time("ns")
    await run_stream(dut, "ddc_rate", words, list(zip(i.tolist(), q.tolist(), strict=True)),
                     lambda d: unpack_iq(d, 16), 1.0, 1.0, setup)
    cycles_per_sample = (get_sim_time("ns") - t0) / 10 / n
    budget = CLK_HZ / cfg.fs
    dut._log.info("throughput: %.2f cycles per input sample; budget %.1f at 100 MHz (%.1fx headroom)",
                  cycles_per_sample, budget, budget / cycles_per_sample)
    ROWS.append(["throughput_no_stall", n, i.size, 0, f"{cycles_per_sample:.2f}", f"{budget:.1f}",
                 f"{budget / cycles_per_sample:.1f}"])
    if os.environ.get("WRITE_RESULTS") == "1":
        from analysis.common import write_result

        verilator = subprocess.run(["verilator", "--version"], capture_output=True, text=True).stdout.split()[1]
        write_result(
            "ddc_rtl_sim",
            ["test", "samples_in", "outputs_checked", "mismatches", "cycles_per_sample", "budget_cycles_100mhz",
             "headroom"],
            ROWS,
            "seeds 8 and 9 in tb/cocotb/test_ddc_top.py (OQPSK, 151 kHz carrier, 30 Hz/s ramp, 6 dB Eb/N0, DC offset)",
            command="make ddc-rtl-results",
            tools=f"Verilator {verilator}, cocotb {cocotb.__version__}",
        )
    assert cycles_per_sample < budget / 4, "less than 4x real-time headroom at a 100 MHz core clock"
