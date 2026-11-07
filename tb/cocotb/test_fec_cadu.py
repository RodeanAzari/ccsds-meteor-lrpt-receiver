"""fec_cadu: frame bits in, CADU bytes and status out, equal to model/coding.py frame_to_cadu() (ADR 0012).

Why it matters: this is where SatDump's CADUs are reproduced byte for byte. A PN that restarts on the wrong bit,
an interleave address off by one, or a codeword written back to the wrong place each corrupt every frame, while a
status word that misreports corrections hides it. The error patterns (0..17 byte errors per codeword, ASM bit errors)
check that the right codeword gets each correction and that an uncorrectable one comes out as received.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from cocotb import start_soon, test
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge
from tb_common import InOrderScoreboard, get_rng
from tb_common.axis import AxisBeat, AxisSink, AxisSource

from model.cadu_fixed import CaduOut
from model.coding import CADU_BITS, build_cadus, frame_to_cadu, nrzm_encode

FRAMES = 6


def _frames(seed: int) -> list[tuple[np.ndarray, tuple[bool, bool, bool]]]:  # type: ignore[type-arg]
    """(plain frame bits as the extractor delivers them, flags) with error patterns per frame."""
    _, on_air = build_cadus(FRAMES, seed)
    rng = np.random.default_rng(seed)
    out = []
    # (byte errors per codeword, ASM bit flips)
    patterns = [((0, 0, 0, 0), 0), ((1, 5, 16, 17), 3), ((16, 16, 16, 16), 0), ((17, 0, 30, 2), 32),
                ((0, 0, 0, 0), 1), ((3, 3, 3, 3), 0)]
    for f in range(FRAMES):
        frame = on_air[f].copy()
        if f == 4:
            frame[4:] = 0  # an all-zero randomized body: derandomizing alone must give the PN
        counts, asm_flips = patterns[f]
        for c, k in enumerate(counts):
            for n in rng.choice(255, size=k, replace=False):
                frame[4 + 4 * int(n) + c] ^= int(rng.integers(1, 256))
        bits = np.unpackbits(frame)
        for b in rng.choice(32, size=asm_flips, replace=False):
            bits[int(b)] ^= 1
        flags = (bool(rng.integers(2)), bool(rng.integers(2)), bool(rng.integers(2)))  # alternate, swap, flywheel
        out.append((bits, flags))
    return out


def _expected(bits: np.ndarray, flags: tuple[bool, bool, bool]) -> tuple[list[int], int]:  # type: ignore[type-arg]
    data, asm_errors, corrections = frame_to_cadu(nrzm_encode(bits), 0)  # undoes to `bits` exactly
    c = CaduOut(data, *flags, asm_errors, corrections)
    return data.tolist(), c.status_word()


async def _run(dut: Any, name: str, frames: list[Any], p_valid: float, p_ready: float,
               bad_last: set[int] = frozenset()) -> InOrderScoreboard:  # type: ignore[assignment]
    start_soon(Clock(dut.clk_i, 10, unit="ns").start())
    rng = get_rng(name)
    dut.rst_i.value = 1
    dut.s_tvalid_i.value = 0
    await ClockCycles(dut.clk_i, 3)
    dut.rst_i.value = 0
    sb = InOrderScoreboard(name)
    got = [0]

    def on_frame(frame: list[AxisBeat]) -> None:
        users = {b.user for b in frame}
        assert len(users) == 1, "tuser changed within a CADU"
        sb.observe(([int(b.data) for b in frame], int(frame[0].user or 0)))
        got[0] += 1

    src = AxisSource(dut, dut.clk_i, "s_", rng=rng, p_valid=p_valid)
    AxisSink(dut, dut.clk_i, "m_", rng=rng, p_ready=p_ready, callback=on_frame)
    beats = []
    for bits, flags in frames:
        sb.expect(_expected(bits, flags))
        user = int(flags[0]) | int(flags[1]) << 1 | int(flags[2]) << 2
        beats += [AxisBeat(int(b), last=i == CADU_BITS - 1, user=user) for i, b in enumerate(bits)]
    for i in bad_last:
        beats[i] = AxisBeat(beats[i].data, last=not beats[i].last, user=beats[i].user)
    await src.send(beats)
    for _ in range(20_000):
        if got[0] == len(frames):
            break
        await RisingEdge(dut.clk_i)
    await ClockCycles(dut.clk_i, 50)
    assert got[0] == len(frames), f"{got[0]} of {len(frames)} CADUs out"
    sb.check_done()
    return sb


@test()
async def cadus_and_status_match_the_model(dut: Any) -> None:
    frames = _frames(21)
    statuses = [_expected(b, f)[1] for b, f in frames]
    # The stimulus spans every RS outcome: clean, corrected, at the limit (16) and failed codewords.
    fields = [(s >> (9 + 6 * c)) & 0x3F for s in statuses for c in range(4)]
    assert {0, 5, 16, 0x20} <= set(fields)
    await _run(dut, "cadu_model", frames, 0.8, 0.7)
    assert int(dut.len_err_o.value) == 0


@test()
async def misplaced_tlast_is_counted_framing_kept(dut: Any) -> None:
    frames = _frames(22)[:3]
    # One early tlast in frame 0, frame 1's real end unmarked.
    await _run(dut, "cadu_tlast", frames, 1.0, 1.0, bad_last={100, 2 * CADU_BITS - 1})
    assert int(dut.len_err_o.value) == 2
