"""sync_top end to end (make sim-full): the RTL chain's soft symbols decode to the transmitted frames.

Why it matters: bit-exactness against the model proves the RTL does what the model does, not that the result is
usable. Here the RTL's own output goes through the model's frame sync, Viterbi, NRZ-M, derandomizer and RS
(receiver.decode_soft()), and the frames that come out must be the ones sent. It is the first time frames come out
of RTL. The loops start cold (AGC from gain 1.0, Costas and timing from zero) on the 1 kHz + 30 Hz/s, 0.37-symbol,
20 ppm input of sync_chain.py, so the run must last past pull-in: in a scratch model run, no frame had decoded by
40,000 of these samples and one had by 60,000. Three frames are sent; the model decodes one of them. Every output is
also checked against the model. Too long for make sim (~4 minutes), so it runs in make sim-full.
"""

from __future__ import annotations

import os
import subprocess

import cocotb
import numpy as np
from cocotb import test
from stream_tb import pack_iq, run_stream, unpack_iq
from sync_chain import ddc_input, expected, set_gains

from model.receiver import data_bytes, decode_soft
from model.sync_fixed import serial

W = 16
FRAMES = 3
SEED = 20


@test()
async def chain_output_decodes_to_sent_frames(dut) -> None:
    i, q, cfg, truth = ddc_input(FRAMES, SEED)
    re, im = expected(i, q, cfg)
    got = await run_stream(dut, "sync_top_full", pack_iq(i, q, W), list(zip(re.tolist(), im.tolist(), strict=True)),
                           lambda d: unpack_iq(d, W), 1.0, 1.0, lambda d: set_gains(d, cfg))
    g_re = np.array([a for a, _ in got])
    g_im = np.array([b for _, b in got])
    soft = serial(g_re, g_im).astype(float)
    cadus = data_bytes(decode_soft(soft / np.mean(np.abs(soft)), cfg).cadus)
    good = sum(bytes(c) in truth for c in cadus)
    dut._log.info("%d samples in, %d outputs; %d CADUs decoded, %d match the %d sent", i.size, len(got), len(cadus),
                  good, FRAMES)
    if os.environ.get("WRITE_RESULTS") == "1":
        from analysis.common import write_result

        verilator = subprocess.run(["verilator", "--version"], capture_output=True, text=True).stdout.split()[1]
        write_result(
            "sync_chain_rtl_decode",
            ["samples_in", "outputs_checked", "mismatches", "frames_sent", "cadus_decoded", "cadus_matching"],
            [[i.size, len(got), 0, FRAMES, len(cadus), good]],
            f"seed {SEED} in tb/cocotb/test_sync_top_full.py via sync_chain.py (bit-true DDC output of OQPSK at 6 dB "
            "Eb/N0, 1 kHz offset + 30 Hz/s before the coarse estimate, 0.37 symbol timing offset, 20 ppm clock; "
            "loops from reset); decoded by model/receiver.py decode_soft()",
            command="make sync-rtl-results",
            tools=f"Verilator {verilator}, cocotb {cocotb.__version__}",
        )
    assert good == len(cadus), f"{len(cadus) - good} decoded CADUs do not match any frame sent"
    assert good >= 1, "no frame decoded from the RTL chain's output"
