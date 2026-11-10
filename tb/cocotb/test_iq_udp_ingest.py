"""iq_udp_ingest: IQ replay datagrams (docs/protocol.md) -> {Q, I} samples, against a model of the format and of
the reorder buffer (ADR 0013).

Why it matters: the board can only be bit-exact against the model if the DDC sees exactly the file's samples, in
order, with nothing from a damaged datagram. A sample let through from a short or truncated datagram shifts every
later sample index (seq * 512) and the whole comparison fails for a reason that isn't in the DDC. The host's network
stack swaps datagrams now and then (board_rx_eth.csv: up to 21 per 34 s replay at 5x); each swap released in arrival
order corrupts 1 ms of signal, a burst of errors that would put a floor under every hardware BER point. Within the
window the ingest must undo the swap; beyond it, a missing datagram must be skipped, not wait forever, and a late
one dropped, not released out of order. The counters are how a hardware run proves nothing was lost on the link, so
their values must be exact, not just non-zero.

The expected output comes from `ingest_model`, written from the rules in the RTL header (ADR 0013), not from its
code: datagrams in arrival order, placed by seq, released in seq order. Runs at DEPTH 2048 (4 slots, the default),
1024 (2 slots) and 512 (one slot: no reordering possible, a swap costs a datagram).
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass

from cocotb import start_soon, test
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge
from tb_common import InOrderScoreboard, get_rng
from tb_common.axis import AxisBeat, AxisSink, AxisSource

SAMPLES = 512  # docs/protocol.md; both parameter sets in tb/cocotb/run.py keep it
LEN = 8 + 2 * SAMPLES


@dataclass
class Dgram:
    payload: bytes
    truncated: bool = False

    @property
    def command(self) -> bool:
        """docs/protocol.md "Control commands": byte 0 bit 7 set. Not replay data, whatever its length."""
        return len(self.payload) > 0 and bool(self.payload[0] & 0x80)

    @property
    def good(self) -> bool:
        return len(self.payload) == LEN and not self.truncated

    @property
    def seq(self) -> int:
        return int.from_bytes(self.payload[:8], "big")

    def samples(self) -> list[int]:
        """{Q, I} words of a good datagram: I is the even byte, Q the odd one (cu8 interleaved I, Q)."""
        d = self.payload[8:]
        return [d[k] | (d[k + 1] << 8) for k in range(0, 2 * SAMPLES, 2)]


def dgram(rng: random.Random, seq: int, length: int = LEN, truncated: bool = False) -> Dgram:
    body = bytes(rng.getrandbits(8) for _ in range(max(0, length - 8)))
    return Dgram((seq.to_bytes(8, "big") + body)[:length], truncated)


def ingest_model(dgrams: list[Dgram], nslot: int) -> tuple[list[int], dict[str, int]]:
    """Released samples and counters, from the RTL header's rules (ADR 0013)."""
    out: list[int] = []
    slots: dict[int, Dgram] = {}
    c = {"ok_cnt_o": 0, "bad_cnt_o": 0, "gap_cnt_o": 0, "lost_cnt_o": 0, "late_cnt_o": 0}
    head = nxt = 0

    def release() -> None:
        nonlocal head
        while head in slots:
            out.extend(slots.pop(head).samples())
            head += 1

    for d in dgrams:
        if d.command:  # ADR 0014: ignored, uncounted (ctrl_rx's)
            continue
        if len(d.payload) > 8 and d.seq >= head + nslot:  # beyond the window: move it, good or not
            while d.seq >= head + nslot:
                if head in slots:
                    release()
                else:
                    c["lost_cnt_o"] += 1
                    head += 1
        if not d.good:
            c["bad_cnt_o"] += 1
        elif d.seq < head or d.seq in slots:
            c["late_cnt_o"] += 1
        else:
            c["ok_cnt_o"] += 1
            c["gap_cnt_o"] += d.seq != nxt
            nxt = d.seq + 1
            slots[d.seq] = d
            release()
    return out, c


async def run(dut, name: str, dgrams: list[Dgram], p_valid: float, p_ready: float, stall: int = 0) -> None:
    """Send the datagrams, check every released sample in order and every counter. With stall = n, the sink holds
    tready low for n clocks before running at p_ready, so the ring fills and s_tready must drop."""
    start_soon(Clock(dut.clk_i, 10, unit="ns").start())
    rng = get_rng(name)
    dut.rst_i.value = 1
    dut.s_tuser_i.value = 0
    await ClockCycles(dut.clk_i, 3)
    dut.rst_i.value = 0

    nslot = int(os.environ.get("PARAM_DEPTH", "2048")) // SAMPLES  # tb/cocotb/run.py; 2048 is the RTL default
    want, counts = ingest_model(dgrams, nslot)
    sb = InOrderScoreboard(name)
    for w in want:
        sb.expect(w)
    sink = AxisSink(dut, dut.clk_i, "m_", rng=rng, p_ready=0.0 if stall else p_ready,
                    callback=lambda f: sb.observe(f[0].data))
    refused = 0

    async def watch_ready() -> None:
        nonlocal refused
        while True:
            await RisingEdge(dut.clk_i)
            refused += int(dut.s_tvalid_i.value == 1 and dut.s_tready_o.value == 0)

    start_soon(watch_ready())
    if stall:
        async def release() -> None:
            await ClockCycles(dut.clk_i, stall)
            sink.p_ready = p_ready
        start_soon(release())

    beats = [AxisBeat(b, last=k == len(d.payload) - 1, user=int(d.truncated and k == len(d.payload) - 1))
             for d in dgrams for k, b in enumerate(d.payload)]
    await AxisSource(dut, dut.clk_i, "s_", rng=rng, p_valid=p_valid).send(beats)
    sink.p_ready = p_ready
    # Drain: up to the whole ring plus a datagram, at 3 clocks per sample at best and 1/p_ready slower
    for _ in range(int((nslot + 1) * SAMPLES * 3 / max(p_ready, 0.1)) + 100):
        if sb.pending == 0:
            break
        await RisingEdge(dut.clk_i)
    await ClockCycles(dut.clk_i, 20)  # nothing extra may come out after the last expected sample
    sb.check_done()
    for sig, n in counts.items():
        got = int(getattr(dut, sig).value)
        assert got == n, f"{sig} = {got}, expected {n}"
    if stall:
        assert refused > 0, "the stalled sink never back-pressured the input: the stall test tested nothing"


def nslot() -> int:
    return int(os.environ.get("PARAM_DEPTH", "2048")) // SAMPLES


@test(timeout_time=5, timeout_unit="ms")  # a deadlocked ring fails instead of hanging
async def clean_stream(dut) -> None:
    """In-order datagrams with random gaps and stalls: every sample out in order, counters ok only.
    Twelve datagrams wrap the ring several times."""
    rng = random.Random(1)
    ds = [dgram(rng, s) for s in range(12)]
    assert ingest_model(ds, nslot())[1]["ok_cnt_o"] == 12
    await run(dut, "ingest_clean", ds, p_valid=0.7, p_ready=0.6)


@test(timeout_time=5, timeout_unit="ms")
async def damaged_datagrams_dropped(dut) -> None:
    """One bad datagram of each kind between good ones: none of their samples may appear, and the good datagram
    with the same seq that follows takes the slot."""
    rng = random.Random(2)
    ds = [
        dgram(rng, 0),
        dgram(rng, 1, length=LEN - 1),      # one byte short: last sample incomplete
        dgram(rng, 1),
        dgram(rng, 2, length=LEN + 1),      # one byte long: SAMPLES samples, then one more byte with tlast
        dgram(rng, 2),
        dgram(rng, 3, truncated=True),      # right length, udp_rx says truncated
        dgram(rng, 3, length=3),            # shorter than the seq field
        dgram(rng, 3, length=LEN - 2),      # whole samples, one short of SAMPLES
        dgram(rng, 3),
        dgram(rng, 4, length=1),
    ]
    assert ingest_model(ds, nslot())[1] == {"ok_cnt_o": 4, "bad_cnt_o": 6, "gap_cnt_o": 0, "lost_cnt_o": 0,
                                            "late_cnt_o": 0}
    await run(dut, "ingest_damaged", ds, p_valid=0.8, p_ready=0.7)


@test(timeout_time=5, timeout_unit="ms")
async def swaps_released_in_seq_order(dut) -> None:
    """What the host does (board_rx_eth.csv): adjacent swaps, and one jump of two. Inside the window every sample
    must come out in file order with nothing lost; with one slot a swap costs the overtaken datagram."""
    rng = random.Random(4)
    order = [0, 2, 1, 3, 4, 6, 5, 7, 10, 8, 9, 11]
    ds = [dgram(rng, s) for s in order]
    samples, c = ingest_model(ds, nslot())
    if nslot() >= 4:
        assert samples == [w for s in range(12) for w in next(d for d in ds if d.seq == s).samples()]
        assert c == {"ok_cnt_o": 12, "bad_cnt_o": 0, "gap_cnt_o": 9, "lost_cnt_o": 0, "late_cnt_o": 0}
    if nslot() == 1:
        assert c["late_cnt_o"] == 4 and c["lost_cnt_o"] == 4  # 1, 5, 8, 9: skipped, then late
    await run(dut, "ingest_swaps", ds, p_valid=0.9, p_ready=0.7)


@test(timeout_time=5, timeout_unit="ms")
async def loss_skipped_late_and_duplicates_dropped(dut) -> None:
    """A datagram that never arrives is skipped once one NSLOT further on needs the window, so the stream goes on;
    when it turns up afterwards it is late and dropped, as is a repeat. A bad datagram far ahead still moves the
    window (its seq is read before the ingest can know it is bad)."""
    rng = random.Random(5)
    ds = [dgram(rng, 0), dgram(rng, 2), dgram(rng, 3), dgram(rng, 4), dgram(rng, 5), dgram(rng, 6),
          dgram(rng, 1),                     # 1 never came in time: skipped, now late
          dgram(rng, 6),                     # duplicate
          dgram(rng, 12, truncated=True),    # bad, but far ahead: the window moves to it
          dgram(rng, 9), dgram(rng, 12)]
    _, c = ingest_model(ds, nslot())
    assert c["lost_cnt_o"] >= 1 and c["late_cnt_o"] >= 2 and c["bad_cnt_o"] == 1
    await run(dut, "ingest_loss", ds, p_valid=0.8, p_ready=0.8)


@test(timeout_time=5, timeout_unit="ms")  # a deadlocked ring fails instead of hanging
async def stalled_sink_fills_ring(dut) -> None:
    """The DDC stops taking samples for longer than the ring holds: s_tready must drop, then everything comes out
    in order once it resumes. Bad datagrams while full (truncated; too long) must still be consumed, not wedge."""
    rng = random.Random(3)
    ds = [dgram(rng, 0), dgram(rng, 1), dgram(rng, 2, truncated=True), dgram(rng, 2, length=LEN + 5), dgram(rng, 2),
          dgram(rng, 3), dgram(rng, 4), dgram(rng, 5)]
    await run(dut, "ingest_stall", ds, p_valid=1.0, p_ready=0.8, stall=16 * SAMPLES)


@test(timeout_time=5, timeout_unit="ms")
async def late_datagram_leaves_no_trace(dut) -> None:
    """A late repeat after its slot has drained: dropped whole, so the datagram that next owns the slot
    (seq + NSLOT) is placed and released normally, and nothing extra comes out. Truncated datagrams (bad, behind
    the window, so harmless) keep the input busy while the ring drains."""
    rng = random.Random(6)
    ds = ([dgram(rng, s) for s in (0, 1, 2, 3)] + [dgram(rng, 0, truncated=True) for _ in range(8)]
          + [dgram(rng, 1)] + [dgram(rng, s) for s in range(4, 12)])
    _, c = ingest_model(ds, nslot())
    assert c == {"ok_cnt_o": 12, "bad_cnt_o": 8, "gap_cnt_o": 0, "lost_cnt_o": 0, "late_cnt_o": 1}
    await run(dut, "ingest_late", ds, p_valid=1.0, p_ready=1.0)


@test(timeout_time=5, timeout_unit="ms")
async def commands_ignored(dut) -> None:
    """Control commands (docs/protocol.md, ADR 0014) share the replay port. Whatever their length, they must leave
    the replay untouched: no sample out, no counter moved, and above all no window move. A command's bytes 0-7 read
    as a seq of at least 2^63, far beyond the window: treated as replay data it would skip every pending datagram as
    lost, or stall the input until they drained. Here commands sit between swapped datagrams, so a window move
    would lose the overtaken one."""
    rng = random.Random(7)
    set_nco = Dgram(bytes.fromhex("80000001") + (0x25C0EE00).to_bytes(4, "big"))
    cmds = [set_nco, Dgram(b"\xff"), Dgram(bytes([0x80]) + bytes(LEN - 1)),  # 1 byte; replay length, seq 2^63
            Dgram(bytes.fromhex("8000000100"), truncated=True), Dgram(bytes([0xC0]) + bytes(20))]
    ds = [dgram(rng, 0), cmds[0], dgram(rng, 2), cmds[1], cmds[2], dgram(rng, 1), dgram(rng, 3), cmds[3],
          dgram(rng, 5), cmds[4], dgram(rng, 4), dgram(rng, 6)]
    samples, c = ingest_model(ds, nslot())
    if nslot() >= 4:
        assert samples == [w for s in range(7) for w in next(d for d in ds if not d.command and d.seq == s).samples()]
        assert c == {"ok_cnt_o": 7, "bad_cnt_o": 0, "gap_cnt_o": 6, "lost_cnt_o": 0, "late_cnt_o": 0}
    await run(dut, "ingest_commands", ds, p_valid=0.9, p_ready=0.7)
