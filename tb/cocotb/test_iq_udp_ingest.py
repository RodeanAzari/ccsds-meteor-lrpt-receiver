"""iq_udp_ingest: IQ replay datagrams (docs/protocol.md) -> {Q, I} samples, against a model of the format.

Why it matters: the board can only be bit-exact against the model if the DDC sees exactly the file's samples, in
order, with nothing from a damaged datagram. A sample let through from a short or truncated datagram shifts every
later sample index (seq * 512) and the whole comparison fails for a reason that isn't in the DDC. The gap counters
are how a hardware run proves nothing was lost on the link, so their values must be exact, not just non-zero.

The expected output is built from the protocol spec, not from the RTL: the concatenated samples of the good
datagrams. Runs at DEPTH 1024 (two datagrams) and DEPTH 512 (= SAMPLES, the smallest legal ring, where a stalled
sink fills the ring mid-datagram).
"""

from __future__ import annotations

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


def expected_counts(dgrams: list[Dgram]) -> dict[str, int]:
    ok = bad = gap = lost = 0
    expect = 0
    for d in dgrams:
        if not d.good:
            bad += 1
            continue
        ok += 1
        if d.seq != expect:
            gap += 1
            lost += max(0, d.seq - expect)
        expect = d.seq + 1
    return {"ok_cnt_o": ok, "bad_cnt_o": bad, "gap_cnt_o": gap, "lost_cnt_o": lost}


async def run(dut, name: str, dgrams: list[Dgram], p_valid: float, p_ready: float, stall: int = 0) -> None:
    """Send the datagrams, check every released sample in order and every counter. With stall = n, the sink holds
    tready low for n clocks before running at p_ready, so the ring fills and s_tready must drop."""
    start_soon(Clock(dut.clk_i, 10, unit="ns").start())
    rng = get_rng(name)
    dut.rst_i.value = 1
    dut.s_tuser_i.value = 0
    await ClockCycles(dut.clk_i, 3)
    dut.rst_i.value = 0

    sb = InOrderScoreboard(name)
    for d in dgrams:
        if d.good:
            for w in d.samples():
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
    for _ in range(4 * SAMPLES * 3 + 100):
        if sb.pending == 0:
            break
        await RisingEdge(dut.clk_i)
    await ClockCycles(dut.clk_i, 20)  # nothing extra may come out after the last expected sample
    sb.check_done()
    for sig, want in expected_counts(dgrams).items():
        got = int(getattr(dut, sig).value)
        assert got == want, f"{sig} = {got}, expected {want}"
    if stall:
        assert refused > 0, "the stalled sink never back-pressured the input: the stall test tested nothing"


@test(timeout_time=5, timeout_unit="ms")  # a deadlocked ring fails instead of hanging
async def clean_stream(dut) -> None:
    """In-order datagrams with random gaps and stalls: every sample out in order, counters ok only.
    Twelve datagrams wrap the ring several times."""
    rng = random.Random(1)
    await run(dut, "ingest_clean", [dgram(rng, s) for s in range(12)], p_valid=0.7, p_ready=0.6)


@test(timeout_time=5, timeout_unit="ms")  # a deadlocked ring fails instead of hanging
async def damaged_and_out_of_sequence(dut) -> None:
    """One bad datagram of each kind between good ones (none of their samples may appear), plus a forward jump of
    3, a repeat and a backward seq. Damaged datagrams don't advance the expected seq."""
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
        dgram(rng, 7),                      # seq 3..6 missing: one gap, 4 lost
        dgram(rng, 8),
        dgram(rng, 8),                      # repeat: gap, no loss
        dgram(rng, 5),                      # backward: gap, no loss
        dgram(rng, 6),
        dgram(rng, 9, length=1),
    ]
    assert expected_counts(ds) == {"ok_cnt_o": 8, "bad_cnt_o": 6, "gap_cnt_o": 3, "lost_cnt_o": 4}
    await run(dut, "ingest_damaged", ds, p_valid=0.8, p_ready=0.7)


@test(timeout_time=5, timeout_unit="ms")  # a deadlocked ring fails instead of hanging
async def stalled_sink_fills_ring(dut) -> None:
    """The DDC stops taking samples for longer than the ring holds: s_tready must drop, then everything comes out
    in order once it resumes. Bad datagrams while full (truncated; too long, whose extra bytes arrive after its samples
filled the ring) must still rewind, not wedge."""
    rng = random.Random(3)
    ds = [dgram(rng, 0), dgram(rng, 1), dgram(rng, 2, truncated=True), dgram(rng, 2, length=LEN + 5), dgram(rng, 2),
          dgram(rng, 3)]
    await run(dut, "ingest_stall", ds, p_valid=1.0, p_ready=0.8, stall=8 * SAMPLES)
