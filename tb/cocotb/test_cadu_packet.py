"""cadu_packet: each CADU becomes one type 2 packet, decoded here from docs/protocol.md's layout with struct.

Why it matters: the ground station parses these bytes by the documented layout; a field one byte off, a status bit
in the wrong place or a CADU byte lost at the header/body seam breaks every packet. A CADU arriving before the host
is known must wait, not vanish.
"""

from __future__ import annotations

import struct
from typing import Any

import numpy as np
from cocotb import start_soon, test
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge
from tb_common import get_rng
from tb_common.axis import AxisBeat, AxisSink, AxisSource

from model.cadu_fixed import CaduOut

CADUS = [
    CaduOut(np.arange(1024, dtype=np.uint8) ^ 0x5A, True, False, True, 3, [0, 5, -1, 16]),
    CaduOut(np.full(1024, 0xFF, dtype=np.uint8), False, True, False, 32, [-1, -1, -1, -1]),
    CaduOut(np.zeros(1024, dtype=np.uint8), False, False, False, 0, [0, 0, 0, 0]),
]


@test()
async def packets_follow_the_protocol(dut: Any) -> None:
    start_soon(Clock(dut.clk_i, 10, unit="ns").start())
    rng = get_rng("cadu_packet")
    dut.rst_i.value = 1
    dut.enable_i.value = 0
    dut.s_tvalid_i.value = 0
    await ClockCycles(dut.clk_i, 3)
    dut.rst_i.value = 0
    packets: list[bytes] = []
    AxisSink(dut, dut.clk_i, "m_", rng=rng, p_ready=0.6,
             callback=lambda f: packets.append(bytes(int(b.data) for b in f)))
    src = AxisSource(dut, dut.clk_i, "s_", rng=rng, p_valid=0.7)
    beats = [AxisBeat(int(x), last=i == 1023, user=c.status_word()) for c in CADUS for i, x in enumerate(c.data)]
    start_soon(src.send(beats))
    # No destination yet: nothing goes out and nothing is taken.
    await ClockCycles(dut.clk_i, 200)
    assert not packets
    assert not dut.s_tready_o.value
    dut.enable_i.value = 1
    for _ in range(20_000):
        if len(packets) == len(CADUS):
            break
        await RisingEdge(dut.clk_i)
    await ClockCycles(dut.clk_i, 50)
    assert len(packets) == len(CADUS)
    uptimes = []
    for seq, (pkt, c) in enumerate(zip(packets, CADUS, strict=True)):
        assert len(pkt) == 16 + 1032
        typ, ver, n, pkt_seq, uptime = struct.unpack(">BBHIQ", pkt[:16])
        assert (typ, ver, n, pkt_seq) == (2, 1, 1032, seq)
        uptimes.append(uptime)
        flags, asm, *rs = pkt[16:22]
        assert flags == int(c.alternate) | int(c.swap) << 1 | int(c.flywheel) << 2
        assert asm == c.asm_errors
        assert rs == [0x80 if x < 0 else x for x in c.corrections]
        assert pkt[22:24] == b"\0\0"
        assert pkt[24:] == bytes(c.data)
    assert uptimes[0] >= 200 and uptimes == sorted(uptimes) and len(set(uptimes)) == len(uptimes)
