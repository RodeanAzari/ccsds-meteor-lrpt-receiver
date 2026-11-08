"""rx_chain end to end (make sim-full): DDC output in, CADUs out of the RTL (Viterbi, NRZ-M, derandomizer, RS),
bit-exact and correct.

Why it matters: each block matches its model alone, but in the chain each one is fed by the RTL block before it, under
its stalls. The soft quantizer's I/Q alternation must stay in step with sync_top's output, the frame sync must find
the frames in the chain's own symbols, and the Viterbi runs the windows back to back without a reset, so each starts
from the metrics the last one left (framesync_fixed.decode_windows()). A link that dropped or repeated a beat, a
wrong window start, or a run-in too short to absorb the previous window would pass every block test and fail here.
Every CADU byte and status word is checked against the bit-true model chain (cadu_fixed.cadus_from_windows() on
decode_windows()), which covers every frame bit the Viterbi emits and the bit before each frame; each CADU must
then be a frame that was sent, ASM included, with no codeword uncorrectable. The loops start cold on sync_chain.py's
input, as in test_sync_top_full.py, so frame 0 is lost to pull-in.

The Viterbi drains windows faster than symbols arrive, so a ready sink would never stall the inner links (CLAUDE.md
§12). The sink holds until the frame sync's ring fills and the stall reaches the chain's input, then holds again
every REHOLD clocks while input remains. The ring can't fill before the input is 32,768 symbols past the oldest
pending window, symbol ~49,000 here, so the stalls only reach data that is checked from the third frame on: with
four frames sent, the only window past that point ended 320 symbols later, and a quantizer that flipped its I/Q
choice on every stalled clock passed (one stall reached checked data). Since Phase E the sink sees whole CADUs:
fec_cadu buffers a frame, so the sink's tready only pushes back once a finished CADU waits, after the first window
has gone through, and once it drains the Viterbi decodes a whole frame (~800,000 clocks) without the sink, emptying
the ring. A stall can then reach the input at most once per waiting CADU (it was every ~44,000 clocks before), and
only if the input still has a full ring (32,768 symbols, two frames) to send past the oldest pending window: the
last CADU's window ends less than two frames before the input does, so its wait never reaches the input. Seven
frames give five CADUs and three stalls (CADUs 2-4); with them, a quantizer flipping I/Q on stalled clocks fails
the byte check (2026-11-08). About 15 minutes, so it runs in make sim-full.
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

from model.cadu_fixed import cadus_from_windows
from model.coding import ASM_BYTES
from model.framesync_fixed import decode_windows, frame_sync_fixed, windows
from model.sync_fixed import serial
from model.viterbi_fixed import TRACEBACK_DEPTH, quantize

W = 16
FRAMES = 7
SEED = 20
SOFT_BITS = 4
SHIFT = 10  # ADR 0005: step ONE/4
THR64 = 48  # RxConfig.sync_threshold * 64
FLYWHEEL = 4  # RxConfig.flywheel
DATA_BYTES = 892  # RS_K * RS_INTERLEAVE: data_bytes()
# Clocks at p_ready 0.5 between holds: long enough for a CADU (1,024 bytes) to drain, then hold again, so the next
# CADU waits from the moment it is ready and its wait backs up through the Viterbi and the ring to the input.
REHOLD = 3_000
MIN_STALLS = 3  # one per CADU but the first and the last; fec_cadu's buffer allows no more (see the docstring)
STALL_CLOCKS = 2000  # input refused this long: a stall from the sink (sync_top alone refuses ~62 clocks per sample)


@test()
async def chain_decodes_sent_frames_bit_exact(dut) -> None:
    i, q, cfg, truth = ddc_input(FRAMES, SEED)
    re, im = expected(i, q, cfg)
    u = quantize(serial(re, im), SOFT_BITS, SHIFT)
    res = frame_sync_fixed(u, THR64, FLYWHEEL)
    wins, early = windows(u, res)
    assert len(wins) >= 3, "the stimulus must give three windows: the third is the one the stalls reach"
    cadus = cadus_from_windows(decode_windows(wins), wins)
    want = np.concatenate([c.data for c in cadus])
    statuses: list[int] = []

    async def watch_status() -> None:
        while True:
            await RisingEdge(dut.clk_i)
            if dut.m_tvalid_o.value and dut.m_tready_i.value and dut.m_tlast_o.value:
                statuses.append(int(dut.m_tuser_o.value))

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
    start_soon(watch_status())
    # The last window drains through the Viterbi after the input ends: ~100 clocks per bit, at the sink's pace.
    steps = len(wins) * (wins[0].pairs.size if wins else 0)
    got = await run_stream(dut, "rx_chain_full", pack_iq(i, q, W), want.tolist(), int, 1.0, 0.5, setup,
                           drain_cycles=4 * 100 * steps, hold_sink_until_stall=STALL_CLOCKS,
                           rehold_after=REHOLD)
    assert statuses == [c.status_word() for c in cadus], "CADU status words differ from the model"
    assert int(dut.flag_ovf_o.value) == 0 and int(dut.len_err_o.value) == 0
    assert stalls >= MIN_STALLS, f"only {stalls} stalls reached the input: the inner links were barely exercised"
    assert int(dut.early_o.value) == early and int(dut.slips_o.value) == res.slips
    assert int(dut.dropped_o.value) == res.dropped and bool(dut.locked_o.value)

    good = sum(
        bytes(c.data[:4]) == ASM_BYTES and bytes(c.data[4 : 4 + DATA_BYTES]) in truth and min(c.corrections) >= 0
        for c in cadus
    )
    rs_fail = sum(x < 0 for c in cadus for x in c.corrections)
    rs_corrected = sum(max(x, 0) for c in cadus for x in c.corrections)
    dut._log.info("%d samples in; %d frames found, %d CADUs bit-exact (%d bytes); %d of %d are a frame sent; RS: %d "
                  "symbols corrected, %d codewords failed; %d input stalls of >= %d clocks", i.size, len(res.frames),
                  len(cadus), len(got), good, len(cadus), rs_corrected, rs_fail, stalls, STALL_CLOCKS)
    if os.environ.get("WRITE_RESULTS") == "1":
        from analysis.common import write_result

        verilator = subprocess.run(["verilator", "--version"], capture_output=True, text=True).stdout.split()[1]
        write_result(
            "rx_chain_rtl_decode",
            ["samples_in", "frames_sent", "frames_found", "cadus", "bytes_checked", "mismatches", "early", "slips",
             "dropped", "rs_symbols_corrected", "rs_codewords_failed", "cadus_matching_sent", "input_stalls"],
            [[i.size, FRAMES, len(res.frames), len(cadus), len(got), 0, early, res.slips, res.dropped, rs_corrected,
              rs_fail, good, stalls]],
            f"seed {SEED} in tb/cocotb/test_rx_chain_full.py via sync_chain.py (bit-true DDC output of OQPSK at 6 dB "
            "Eb/N0, 1 kHz offset + 30 Hz/s before the coarse estimate, 0.37 symbol timing offset, 20 ppm clock; "
            "loops from reset); CADUs out of the RTL after NRZ-M, derandomizer and RS",
            command="make fec-rtl-results",
            tools=f"Verilator {verilator}, cocotb {cocotb.__version__}",
        )
    assert good == len(cadus), f"{len(cadus) - good} CADUs are no frame sent"
