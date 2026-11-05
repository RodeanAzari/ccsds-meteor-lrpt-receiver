"""sync_rrc: 57-tap RRC matched filter, bit-exact against model/rrc_fixed.py rrc_fixed().

Why it matters: the RRC is half of the raised-cosine pulse; only with the transmit RRC does it give zero ISI at the
symbol strobes. A wrong tap, a history off by one, or a tap file that drifts from the model makes the timing and
carrier loops downstream lock onto a smeared constellation. The modulated test feeds what the RRC really sees, the
bit-true DDC output; the impulse checks the pulse is centred; the worst case exercises saturation, which the
in-range signal never reaches.
"""

from __future__ import annotations

import os
import subprocess

import cocotb
import numpy as np
from cocotb import test
from cocotb.utils import get_sim_time
from stream_tb import pack_iq, run_stream, unpack_iq

from model import ddc_fixed, rrc_fixed
from model.channel import TxConfig, apply_carrier, awgn, modulate, noise_sigma, to_cu8
from model.coding import build_cadus, encode_stream
from model.receiver import RxConfig

W = 16
TAPS = rrc_fixed.taps(RxConfig())
CLK_HZ = 100e6  # planned core clock (CLAUDE.md §3.3)
ROWS: list[list[object]] = []  # filled by each test; written by the last one when WRITE_RESULTS=1


async def run(dut, i: np.ndarray, q: np.ndarray, cfg: RxConfig, name: str, p_valid: float, p_ready: float):
    ei, eq = rrc_fixed.rrc_fixed(i, q, cfg)
    expected = list(zip(ei.tolist(), eq.tolist(), strict=True))
    return await run_stream(dut, name, pack_iq(i, q, W), expected, lambda d: unpack_iq(d, W), p_valid, p_ready)


@test()
async def modulated_signal_backpressure(dut) -> None:
    """Bit-true DDC output of OQPSK frames (6 dB, 151 kHz off, 30 Hz/s ramp), random stalls on both sides."""
    tx = TxConfig()
    _, on_air = build_cadus(1, 11)
    sigma = noise_sigma(6.0, tx.fs)
    x = awgn(apply_carrier(modulate(encode_stream(on_air), tx), tx.fs, 151_000.0, 30.0, 0.7), sigma, 11)[:16_000]
    cfg = RxConfig(fs=tx.fs, tune_offset_hz=150_000.0)
    i, q = ddc_fixed.ddc_fixed_rails(to_cu8(x, full_scale=4 * sigma), cfg)
    got = await run(dut, i, q, cfg, "rrc_modulated", 0.7, 0.6)
    ROWS.append(["bit_exact_backpressure", i.size, len(got), 0, "", "", ""])


@test()
async def impulse_is_centred(dut) -> None:
    """An impulse on I (+) and Q (-): the response peaks at the centre tap, symmetric, and mirrored on Q."""
    n = 2 * TAPS.size
    i = np.zeros(n, dtype=np.int64)
    q = np.zeros(n, dtype=np.int64)
    i[0], q[0] = 32767, -32768
    got = await run(dut, i, q, RxConfig(), "rrc_impulse", 1.0, 1.0)
    resp = np.array([a for a, _ in got[: TAPS.size]])
    assert int(np.argmax(resp)) == TAPS.size // 2, "RRC impulse response is not centred"
    assert (resp == resp[::-1]).all(), "RRC impulse response is not symmetric"


@test()
async def worst_case_saturates(dut) -> None:
    """Full-scale input signed like the taps: sum |h| = 1.374 overflows s16, so the output must clip, not wrap."""
    sign = np.sign(TAPS[::-1]).astype(np.int64)
    i = np.tile(32767 * sign, 3)
    q = -i
    got = await run(dut, i, q, RxConfig(), "rrc_saturate", 0.8, 0.8)
    assert (32767, -32768) in got, "worst-case input never reached the saturation limits"


@test()
async def throughput_leaves_real_time_margin(dut) -> None:
    """With the output always ready, the RRC must take a 256 kS/s stream with at least 4x real-time headroom.

    It sets how fast BER-campaign files can be replayed into the RRC-input injection mux (CLAUDE.md §8.4).
    """
    cfg = RxConfig()
    n = 2000
    rng = np.random.default_rng(12)
    i = np.round(3000 * rng.standard_normal(n)).astype(np.int64)
    q = np.round(3000 * rng.standard_normal(n)).astype(np.int64)
    t0 = get_sim_time("ns")
    await run(dut, i, q, cfg, "rrc_rate", 1.0, 1.0)
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
            "rrc_rtl_sim",
            ["test", "samples_in", "outputs_checked", "mismatches", "cycles_per_sample", "budget_cycles_100mhz",
             "headroom"],
            ROWS,
            "seeds 11 and 12 in tb/cocotb/test_sync_rrc.py (bit-true DDC output of OQPSK at 6 dB Eb/N0, 151 kHz "
            "carrier, 30 Hz/s ramp; Gaussian noise for the rate)",
            command="make sync-rtl-results",
            tools=f"Verilator {verilator}, cocotb {cocotb.__version__}",
        )
    assert cycles_per_sample < budget / 4, "less than 4x real-time headroom at a 100 MHz core clock"
