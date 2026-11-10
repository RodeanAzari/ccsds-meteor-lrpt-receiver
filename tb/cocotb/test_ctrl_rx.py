"""ctrl_rx: control commands (docs/protocol.md "Control commands", ADR 0014) read off the replay datagram stream.

Why it matters: the NCO word decides whether the receiver decodes anything at all (a word off by the coarse
estimate's error leaves the carrier outside the Costas loop's pull-in, progress.md). A replay datagram mistaken for
a command would retune the DDC mid-recording; a malformed command accepted would set a garbage word; a word
accepted after the DDC started would mix two words into one replay, which no model run reproduces. The host checks
the word in the stats packet, and the counters are how it learns a command was refused, so they must be exact.

`model` is written from docs/protocol.md's rules: a command is a datagram whose byte 0 has bit 7 set; SET_NCO is
exactly 8 bytes, 0x80000001 then the word, not truncated; accepted only while lock_i is low.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from cocotb import start_soon, test
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge

SET_NCO = 0x8000_0001  # docs/protocol.md "Control commands"


@dataclass
class Dgram:
    payload: bytes
    truncated: bool = False
    locked: bool = False  # lock_i while this datagram is sent


def set_nco(word: int, **kw: bool) -> Dgram:
    return Dgram(SET_NCO.to_bytes(4, "big") + word.to_bytes(4, "big"), **kw)


def model(ds: list[Dgram]) -> tuple[list[int], int, int]:
    """Words accepted in order, ok count, bad count."""
    words: list[int] = []
    bad = 0
    for d in ds:
        if not d.payload or not d.payload[0] & 0x80:
            continue
        p = d.payload
        if len(p) == 8 and not d.truncated and int.from_bytes(p[:4], "big") == SET_NCO and not d.locked:
            words.append(int.from_bytes(p[4:], "big"))
        else:
            bad += 1
    return words, len(words), bad


async def run(dut, ds: list[Dgram], rng: random.Random, p_beat: float) -> None:
    """From reset: send the datagrams, then check the words set and the counters. The clock is the test's."""
    for sig in (dut.s_beat_i, dut.s_tlast_i, dut.s_tuser_i, dut.lock_i, dut.s_tdata_i):
        sig.value = 0
    dut.rst_i.value = 1
    await ClockCycles(dut.clk_i, 3)
    dut.rst_i.value = 0

    got: list[int] = []

    async def monitor() -> None:
        while True:
            await RisingEdge(dut.clk_i)
            if dut.set_o.value == 1:
                got.append(int(dut.word_o.value))

    mon = start_soon(monitor())
    for d in ds:
        for k, b in enumerate(d.payload):
            while rng.random() > p_beat:  # idle clocks between beats: no beat, garbage on the data lines
                await FallingEdge(dut.clk_i)
                dut.lock_i.value = int(d.locked)  # changes only after the previous datagram's last beat
                dut.s_beat_i.value = 0
                dut.s_tdata_i.value = rng.getrandbits(8)
                dut.s_tlast_i.value = rng.getrandbits(1)
                dut.s_tuser_i.value = rng.getrandbits(1)
            await FallingEdge(dut.clk_i)
            last = k == len(d.payload) - 1
            dut.lock_i.value = int(d.locked)
            dut.s_beat_i.value = 1
            dut.s_tdata_i.value = b
            dut.s_tlast_i.value = int(last)
            dut.s_tuser_i.value = int(last and d.truncated)
    await FallingEdge(dut.clk_i)
    dut.s_beat_i.value = 0
    await ClockCycles(dut.clk_i, 3)
    mon.cancel()

    words, ok, bad = model(ds)
    assert got == words, f"words set {[hex(w) for w in got]}, expected {[hex(w) for w in words]}"
    assert int(dut.ok_cnt_o.value) == ok, f"ok_cnt {int(dut.ok_cnt_o.value)}, expected {ok}"
    assert int(dut.bad_cnt_o.value) == bad, f"bad_cnt {int(dut.bad_cnt_o.value)}, expected {bad}"


def replay(rng: random.Random, seq: int) -> Dgram:
    return Dgram(seq.to_bytes(8, "big") + bytes(rng.getrandbits(8) for _ in range(24)))  # short: the length is moot


@test()
async def commands_among_replay(dut) -> None:
    """Every kind of datagram the port can carry, back to back and with idle clocks: only well-formed SET_NCO
    commands while unlocked set a word; each command datagram counts once as ok or bad; replay datagrams (bit 7
    clear), even one whose bytes 0-7 read 0x80000001 after the first byte, never count. Includes a replay datagram
    carrying the SET_NCO pattern at bytes 8-15 (the command must start at byte 0)."""
    start_soon(Clock(dut.clk_i, 10, unit="ns").start())
    rng = random.Random(11)
    ds = [
        replay(rng, 0),
        set_nco(0x25C0_EE00),
        Dgram(bytes(8) + SET_NCO.to_bytes(4, "big") + bytes(4)),  # replay seq 0 with the pattern at byte 8
        set_nco(0x1234_5678, truncated=True),
        Dgram(set_nco(0xAAAA_AAAA).payload[:7]),                  # one byte short
        Dgram(set_nco(0xBBBB_BBBB).payload + b"\0"),              # one byte long
        Dgram(bytes.fromhex("80000002") + bytes(4)),              # unknown command
        Dgram(bytes.fromhex("80")),                               # one byte
        Dgram(bytes.fromhex("00000001") + bytes(4)),              # SET_NCO without bit 31: 8-byte replay datagram
        set_nco(0xFFFF_FFFF),
        replay(rng, 1),
        set_nco(0x0000_0001),
        set_nco(0x8000_0000),
        Dgram(bytes(9) + bytes.fromhex("80000001aabbcc")),        # replay ending in the SET_NCO pattern, then
        Dgram(bytes.fromhex("dd")),                               # a 1-byte command: its 8 last bytes look valid
    ]
    assert model(ds) == ([0x25C0_EE00, 0xFFFF_FFFF, 0x0000_0001, 0x8000_0000], 4, 6)
    await run(dut, ds, rng, p_beat=1.0)
    await run(dut, ds, rng, p_beat=0.5)


@test()
async def refused_while_locked(dut) -> None:
    """Once the DDC has taken a sample (lock_i high) a SET_NCO is refused and counted bad; while unlocked the same
    command is accepted. Random sequence of good commands with lock toggling."""
    start_soon(Clock(dut.clk_i, 10, unit="ns").start())
    rng = random.Random(12)
    ds = [set_nco(rng.getrandbits(32), locked=rng.random() < 0.5) for _ in range(40)]
    _, ok, bad = model(ds)
    assert ok > 5 and bad > 5
    await run(dut, ds, rng, p_beat=0.7)
