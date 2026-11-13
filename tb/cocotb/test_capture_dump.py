"""capture_dump: the Phase B board readout (stream words -> BRAM -> UART bytes).

Why it matters: scripts/ddc_board.py compares every dumped word with the bit-true model, so a lost, repeated or
reordered word, a wrong count in the header or a wrong CRC-32 turns into a false DDC failure on the board. Once the
buffer is full the input must be held (s_tready low), never taken and dropped: the replay keeps sending after the
capture window, and a word taken past the end would overwrite or vanish silently. dump_i sends the same buffer again.
"""

from __future__ import annotations

import struct
import zlib
from typing import Any

from cocotb import start_soon, test
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge
from tb_common import get_rng
from tb_common.axis import AxisBeat, AxisSink, AxisSource

N_WORDS = 64  # tb/cocotb/run.py parameter
EXTRA = 3  # words offered after the buffer is full: must be held


def dump_size(n: int) -> int:  # "DDC1" | u32 n | n x u32 | u32 CRC-32 (rtl/io/capture_dump.sv header)
    return 8 + 4 * n + 4


async def read_dump(dut: Any, sink: AxisSink, start: int) -> bytes:
    while sink.beats_seen < start + dump_size(N_WORDS):
        await RisingEdge(dut.clk_i)
    return bytes(f[0].data for f in sink.frames[start:start + dump_size(N_WORDS)])


def check_dump(data: bytes, words: list[int]) -> None:
    assert data[:4] == b"DDC1", f"bad magic {data[:4]!r}"
    assert struct.unpack_from("<I", data, 4)[0] == N_WORDS, "header word count"
    got = list(struct.unpack_from(f"<{N_WORDS}I", data, 8))
    bad = [i for i, (g, w) in enumerate(zip(got, words, strict=True)) if g != w]
    assert not bad, f"{len(bad)} words differ, first at {bad[0]}: {got[bad[0]]:#x} != {words[bad[0]]:#x}"
    assert struct.unpack_from("<I", data, 8 + 4 * N_WORDS)[0] == zlib.crc32(data[:8 + 4 * N_WORDS]), "CRC-32"


@test()
async def full_buffer_holds_input_and_dumps_twice(dut: Any) -> None:
    rng = get_rng("capture_dump")
    start_soon(Clock(dut.clk_i, 10, unit="ns").start())
    dut.rst_i.value = 1
    dut.dump_i.value = 0
    source = AxisSource(dut, dut.clk_i, "s_", rng, p_valid=0.7)
    sink = AxisSink(dut, dut.clk_i, "m_", rng, p_ready=0.6)
    await ClockCycles(dut.clk_i, 3)
    dut.rst_i.value = 0

    words = [rng.getrandbits(32) for _ in range(N_WORDS + EXTRA)]
    start_soon(source.send(AxisBeat(w) for w in words))  # never finishes: the extra words are held
    check_dump(await read_dump(dut, sink, 0), words[:N_WORDS])
    assert int(dut.full_o.value) == 1
    assert source.beats_sent == N_WORDS, f"{source.beats_sent - N_WORDS} words taken past a full buffer"
    assert int(dut.s_tvalid_i.value) == 1 and int(dut.s_tready_o.value) == 0, "the next word is not being held"

    while int(dut.busy_o.value):
        await RisingEdge(dut.clk_i)
    dut.dump_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.dump_i.value = 0
    check_dump(await read_dump(dut, sink, dump_size(N_WORDS)), words[:N_WORDS])
    assert source.beats_sent == N_WORDS, "a word was taken during the repeat dump"
