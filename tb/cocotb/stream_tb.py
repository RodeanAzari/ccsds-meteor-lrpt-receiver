"""Shared harness: drive one-word-per-beat AXI-Stream input, check every output beat in order against the model."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from cocotb import start_soon
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge
from tb_common import InOrderScoreboard, get_rng
from tb_common.axis import AxisBeat, AxisSink, AxisSource


def signed(v: int, bits: int) -> int:
    return v - (1 << bits) if v >> (bits - 1) else v


def pack_iq(i: Sequence[int], q: Sequence[int], bits: int) -> list[int]:
    """{Q, I} words, each rail `bits` wide (the DDC's tdata layout)."""
    mask = (1 << bits) - 1
    return [(int(a) & mask) | ((int(b) & mask) << bits) for a, b in zip(i, q, strict=True)]


def unpack_iq(word: int, bits: int) -> tuple[int, int]:
    return signed(word & ((1 << bits) - 1), bits), signed(word >> bits, bits)


async def run_stream(
    dut: Any,
    name: str,
    words: Sequence[int],
    expected: Sequence[Any],
    decode: Callable[[int], Any],
    p_valid: float,
    p_ready: float,
    setup: Callable[[Any], None] | None = None,
) -> list[Any]:
    """Reset, stream `words` into s_*, check decode(m_tdata) against `expected` in order; return what came out."""
    start_soon(Clock(dut.clk_i, 10, unit="ns").start())
    rng = get_rng(name)
    dut.rst_i.value = 1
    dut.s_tvalid_i.value = 0
    if setup is not None:
        setup(dut)
    await ClockCycles(dut.clk_i, 3)
    dut.rst_i.value = 0

    sb = InOrderScoreboard(name)
    for e in expected:
        sb.expect(e)
    got: list[Any] = []

    def on_beat(frame: list[AxisBeat]) -> None:
        item = decode(frame[0].data)
        got.append(item)
        sb.observe(item)

    AxisSink(dut, dut.clk_i, "m_", rng=rng, p_ready=p_ready, callback=on_beat)
    src = AxisSource(dut, dut.clk_i, "s_", rng=rng, p_valid=p_valid)
    await src.send(AxisBeat(w) for w in words)
    for _ in range(200):
        if sb.pending == 0:
            break
        await RisingEdge(dut.clk_i)
    sb.check_done()
    return got
