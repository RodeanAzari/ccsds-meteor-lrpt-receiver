"""pkt_arb2: two packet streams merged whole for udp_tx.

Why it matters: udp_tx sends one UDP payload per tlast, so a byte from the other source inside a packet, a lost or
repeated byte, or a packet out of order corrupts what the host parses (docs/protocol.md). Every output packet must
equal the next pending packet of exactly one source, and all of them must come out. The CADU stream can be busy for
long stretches; with both sources always ready, packets must alternate, or the stats packets (the replay's only
health readout) could wait behind CADUs indefinitely.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from cocotb import start_soon, test
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge
from tb_common import get_rng
from tb_common.axis import AxisBeat, AxisSink, AxisSource


async def reset(dut: Any) -> None:
    start_soon(Clock(dut.clk_i, 10, unit="ns").start())
    dut.rst_i.value = 1
    dut.s0_tvalid_i.value = 0
    dut.s1_tvalid_i.value = 0
    await ClockCycles(dut.clk_i, 3)
    dut.rst_i.value = 0


def beats(packets: list[bytes]) -> list[AxisBeat]:
    return [AxisBeat(b, last=i == len(p) - 1) for p in packets for i, b in enumerate(p)]


async def merge(dut: Any, name: str, n0: int, n1: int, p_valid: float, p_ready: float) -> list[tuple[int, bytes]]:
    """Send n0 / n1 random packets on s0 / s1; return (source, packet) for each output packet, checked whole."""
    rng = get_rng(name)
    await reset(dut)
    sent = [[bytes(rng.randrange(256) for _ in range(rng.randint(1, 40))) for _ in range(n)] for n in (n0, n1)]
    pending = [deque(sent[0]), deque(sent[1])]
    order: list[tuple[int, bytes]] = []

    def on_packet(frame: list[AxisBeat]) -> None:
        pkt = bytes(int(b.data) for b in frame)
        hits = [k for k in (0, 1) if pending[k] and pending[k][0] == pkt]
        assert hits, f"packet {len(order)} ({len(pkt)} bytes) is no source's next packet: interleaved or corrupted"
        k = hits[0]  # equal heads on both sides are indistinguishable and harmless
        pending[k].popleft()
        order.append((k, pkt))

    AxisSink(dut, dut.clk_i, "m_", rng=rng, p_ready=p_ready, callback=on_packet)
    srcs = [AxisSource(dut, dut.clk_i, f"s{k}_", rng=rng, p_valid=p_valid) for k in (0, 1)]
    for k in (0, 1):
        start_soon(srcs[k].send(beats(sent[k])))
    for _ in range(200 * (n0 + n1) * 40):
        if not pending[0] and not pending[1]:
            break
        await RisingEdge(dut.clk_i)
    assert not pending[0] and not pending[1], f"packets never sent: {len(pending[0])} on s0, {len(pending[1])} on s1"
    return order


@test()
async def random_handshakes_keep_packets_whole(dut: Any) -> None:
    order = await merge(dut, "pkt_arb2_random", 60, 60, 0.6, 0.6)
    assert {k for k, _ in order} == {0, 1}


@test()
async def one_source_alone(dut: Any) -> None:
    order = await merge(dut, "pkt_arb2_alone", 0, 25, 0.8, 0.5)
    assert [k for k, _ in order] == [1] * 25


@test()
async def saturated_sources_alternate(dut: Any) -> None:
    order = await merge(dut, "pkt_arb2_fair", 20, 20, 1.0, 1.0)
    assert [k for k, _ in order] == [0, 1] * 20, "both sources always valid: the grant must alternate"


@test()
async def stalled_sink_takes_nothing(dut: Any) -> None:
    """A stalled sink: no source sees tready, so neither loses a byte while the other waits."""
    rng = get_rng("pkt_arb2_stall")
    await reset(dut)
    srcs = [AxisSource(dut, dut.clk_i, f"s{k}_", rng=rng) for k in (0, 1)]
    dut.m_tready_i.value = 0
    for k in (0, 1):
        start_soon(srcs[k].send(beats([bytes([k + 1] * 5)])))
    for _ in range(50):
        await RisingEdge(dut.clk_i)
        assert not dut.s0_tready_o.value and not dut.s1_tready_o.value
