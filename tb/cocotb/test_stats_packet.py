"""stats_packet: periodic stats payloads (docs/protocol.md "Board → host packets", "Stats"), parsed by the host's
reference parser.

Why it matters: the host reads loss counters from these packets. A packet whose fields come from different clocks,
a truncated or interleaved packet under backpressure, or a skipped pkt_seq would make the counters lie. The fields
here change every clock (field k = cycle + k), so any packet not snapshotted on one clock shows f[k] - f[0] != k.
PERIOD (60) is shorter than a packet (88 bytes) and the sink stalls at random, so ticks arrive while a packet is
still going out: the pending path must delay the next packet, not drop, cut or merge it.
"""

from __future__ import annotations

from cocotb import start_soon, test
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge
from tb_common import get_rng
from tb_common.axis import AxisSink

from scripts.board_stats import FIELDS, parse_stats

N = 18  # tb/cocotb/run.py N_FIELDS
PERIOD = 60  # tb/cocotb/run.py PERIOD


async def drive_fields(dut) -> None:
    cycle = 0
    while True:
        dut.fields_i.value = sum(((cycle + k) & 0xFFFF_FFFF) << (32 * k) for k in range(N))
        await RisingEdge(dut.clk_i)
        cycle += 1


async def run(dut, name: str, p_ready: float, n_packets: int) -> list[bytes]:
    start_soon(Clock(dut.clk_i, 10, unit="ns").start())
    dut.rst_i.value = 1
    dut.enable_i.value = 0
    start_soon(drive_fields(dut))
    pkts: list[bytes] = []
    AxisSink(dut, dut.clk_i, "m_", rng=get_rng(name), p_ready=p_ready,
             callback=lambda f: pkts.append(bytes(b.data for b in f)))
    await ClockCycles(dut.clk_i, 3)
    dut.rst_i.value = 0
    await ClockCycles(dut.clk_i, 3 * PERIOD)
    assert not pkts, "sent while enable_i was low"
    dut.enable_i.value = 1
    for _ in range(n_packets * 400):
        await RisingEdge(dut.clk_i)
        if len(pkts) >= n_packets:
            break
    assert len(pkts) >= n_packets, f"only {len(pkts)} packets"
    return pkts


def check(pkts: list[bytes], min_gap: int, exact: bool = False) -> None:
    prev = None
    for raw in pkts:
        s = parse_stats(raw)  # raises on a cut, merged or malformed packet
        f = [s.fields[k] for k in FIELDS[:N]]
        assert all(f[k] - f[0] == k for k in range(N)), f"packet {s.pkt_seq}: fields from different clocks: {f}"
        if prev is not None:
            assert s.pkt_seq == prev.pkt_seq + 1, f"pkt_seq {prev.pkt_seq} -> {s.pkt_seq}"
            gap = s.uptime - prev.uptime
            assert gap == min_gap if exact else gap >= min_gap, f"packets {gap} cycles apart (min {min_gap})"
        prev = s


@test()
async def full_rate_sink(dut) -> None:
    """Sink always ready: a packet (88 beats) is longer than PERIOD, so a tick always arrives during it and every
    packet but the first starts from that pending tick on the previous packet's last beat: exactly 88 clocks apart.
    Without the pending tick they would be 2 x PERIOD = 120 apart."""
    check(await run(dut, "stats_full", 1.0, 20), 88, exact=True)


@test()
async def stalling_sink(dut) -> None:
    """Random stalls: packets stay whole, in order, each self-consistent."""
    check(await run(dut, "stats_stall", 0.4, 15), 88)
