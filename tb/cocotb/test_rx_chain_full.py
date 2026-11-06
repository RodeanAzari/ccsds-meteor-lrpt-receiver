"""rx_chain end to end (make sim-full): DDC output in, decoded bits out of the RTL Viterbi, bit-exact and correct.

Why it matters: each block matches its model alone, but in the chain each one is fed by the RTL block before it, under
its stalls. The soft quantizer's I/Q alternation must stay in step with sync_top's output, the frame sync must find
the frames in the chain's own symbols, and the Viterbi runs the windows back to back without a reset, so each starts
from the metrics the last one left (framesync_fixed.decode_windows()). A link that dropped or repeated a beat, a
wrong window start, or a run-in too short to absorb the previous window would pass every block test and fail here.
Every output bit is checked against the bit-true model chain, then each window's frame is NRZ-M decoded and
derandomized and must be a frame that was sent, ASM included, before RS. The loops start cold on sync_chain.py's
input, as in test_sync_top_full.py, so frame 0 is lost to pull-in.

The Viterbi drains windows faster than symbols arrive, so a ready sink would never stall the inner links (CLAUDE.md
§12). The sink holds until the frame sync's ring fills and the stall reaches the chain's input, then holds again
every REHOLD clocks while input remains. The ring can't fill before the input is 32,768 symbols past the oldest
pending window, symbol ~49,000 here, so the stalls only reach data that is checked from the third frame on: with
four frames sent, the only window past that point ended 320 symbols later, and a quantizer that flipped its I/Q
choice on every stalled clock passed (one stall reached checked data). Five frames sent
give three windows, the last with ~40 stalls inside it. About 10 minutes, so it runs in make sim-full.
"""

from __future__ import annotations

import os
import subprocess

import cocotb
import numpy as np
from cocotb import start_soon, test
from cocotb.triggers import RisingEdge
from stream_tb import pack_iq, run_stream
from sync_chain import ddc_input, expected, set_gains

from model.coding import ASM_BYTES, CADU_BITS, nrzm_decode, randomize
from model.framesync_fixed import PRE_SYMBOLS, decode_windows, frame_sync_fixed, windows
from model.sync_fixed import serial
from model.viterbi_fixed import TRACEBACK_DEPTH, TRACEBACK_START, path_metric_bits, quantize, viterbi_fixed

W = 16
FRAMES = 5
SEED = 20
SOFT_BITS = 4
SHIFT = 10  # ADR 0005: step ONE/4
THR64 = 48  # RxConfig.sync_threshold * 64
FLYWHEEL = 4  # RxConfig.flywheel
DATA_BYTES = 892  # RS_K * RS_INTERLEAVE: data_bytes()
REHOLD = 20_000  # clocks at p_ready 0.5 between holds: the Viterbi frees ~400 ring symbols, refilled in ~44,000
MIN_STALLS = 20
STALL_CLOCKS = 2000  # input refused this long: a stall from the sink (sync_top alone refuses ~62 clocks per sample)


@test()
async def chain_decodes_sent_frames_bit_exact(dut) -> None:
    i, q, cfg, truth = ddc_input(FRAMES, SEED)
    re, im = expected(i, q, cfg)
    u = quantize(serial(re, im), SOFT_BITS, SHIFT)
    res = frame_sync_fixed(u, THR64, FLYWHEEL)
    wins, early = windows(u, res)
    assert len(wins) >= 3, "the stimulus must give three windows: the third is the one the stalls reach"
    pairs = np.concatenate([w.pairs for w in wins])
    sym = np.empty(2 * pairs.size, dtype=np.int64)
    sym[0::2], sym[1::2] = pairs & 15, pairs >> 4
    bits, _ = viterbi_fixed(sym, SOFT_BITS, path_metric_bits(SOFT_BITS), TRACEBACK_DEPTH, TRACEBACK_START)
    want = bits[: pairs.size - TRACEBACK_DEPTH]  # the last depth bits wait for input that never comes

    def setup(d) -> None:
        set_gains(d, cfg)
        d.thr64_i.value = THR64
        d.flywheel_i.value = FLYWHEEL
        d.depth_i.value = TRACEBACK_DEPTH

    stalls = 0

    async def count_stalls() -> None:
        nonlocal stalls
        run = 0
        while True:
            await RisingEdge(dut.clk_i)
            run = run + 1 if bool(dut.s_tvalid_i.value) and not bool(dut.s_tready_o.value) else 0
            stalls += run == STALL_CLOCKS

    start_soon(count_stalls())
    # The last window drains through the Viterbi after the input ends: ~100 clocks per bit, at the sink's pace.
    got = await run_stream(dut, "rx_chain_full", pack_iq(i, q, W), want.tolist(), int, 1.0, 0.5, setup,
                           drain_cycles=4 * 100 * pairs.size, hold_sink_until_stall=STALL_CLOCKS,
                           rehold_after=REHOLD)
    assert stalls >= MIN_STALLS, f"only {stalls} stalls reached the input: the inner links were barely exercised"
    assert int(dut.early_o.value) == early and int(dut.slips_o.value) == res.slips
    assert int(dut.dropped_o.value) == res.dropped and bool(dut.locked_o.value)

    first = PRE_SYMBOLS // 2
    good = 0
    for b in decode_windows(wins):  # equal to the RTL's bits: checked beat for beat above
        frame = np.packbits(nrzm_decode(b[first : first + CADU_BITS], int(b[first - 1])))
        good += bytes(frame[:4]) == ASM_BYTES and bytes(randomize(frame[4:])[:DATA_BYTES]) in truth
    dut._log.info("%d samples in; %d frames found, %d windows, %d bits bit-exact; %d of %d frames decode to a frame "
                  "sent; %d input stalls of >= %d clocks", i.size, len(res.frames), len(wins), len(got), good,
                  len(wins), stalls, STALL_CLOCKS)
    if os.environ.get("WRITE_RESULTS") == "1":
        from analysis.common import write_result

        verilator = subprocess.run(["verilator", "--version"], capture_output=True, text=True).stdout.split()[1]
        write_result(
            "rx_chain_rtl_decode",
            ["samples_in", "frames_sent", "frames_found", "windows", "bits_checked", "mismatches", "early", "slips",
             "dropped", "frames_matching_sent", "input_stalls"],
            [[i.size, FRAMES, len(res.frames), len(wins), len(got), 0, early, res.slips, res.dropped, good, stalls]],
            f"seed {SEED} in tb/cocotb/test_rx_chain_full.py via sync_chain.py (bit-true DDC output of OQPSK at 6 dB "
            "Eb/N0, 1 kHz offset + 30 Hz/s before the coarse estimate, 0.37 symbol timing offset, 20 ppm clock; "
            "loops from reset); frames checked after NRZ-M and derandomizing, before RS",
            command="make fec-rtl-results",
            tools=f"Verilator {verilator}, cocotb {cocotb.__version__}",
        )
    assert good == len(wins), f"{len(wins) - good} windows decode to no frame sent"
