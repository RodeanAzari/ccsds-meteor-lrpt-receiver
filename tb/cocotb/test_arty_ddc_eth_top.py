"""arty_ddc_eth_top: the Ethernet-fed board design, from the PHY's MII pins to the UART and MII TX pins.

Why it matters: on the board the evidence is the bytes on the serial line after gs-replay streams the snippet,
and the stats packets the board sends back. This test sends the same snippet as replay datagrams
(docs/protocol.md), built here from the RFCs and the protocol doc, as MII nibbles at 25 MHz, then decodes the UART
dump exactly as scripts/ddc_board.py will and compares every DDC output with the bit-true model. A failure on
hardware then points at the board or the link, not the design.
It also covers the top's own wiring: the multicast group and port the defaults select, the PHY reset released
after start-up, that frames which must not reach the DDC (bad FCS, another port) don't, and that the stats packets
(docs/protocol.md "Stats") go to the replay's sender with every counter equal to what was sent: the hardware
campaign blames lost datagrams on a stage by these counters, so a miswired one would blame the wrong stage.
The MMCM stand-in passes clk100 through, so the core runs at 100 MHz here as on the board.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from cocotb import start_soon, test
from cocotb.clock import Clock
from cocotb.handle import Force, Release
from cocotb.triggers import ClockCycles
from ddc_board import N_SIM, expected_sim, uart_bytes
from mii import collect_mii_tx, parse_udp_frame, send_mii, udp_frame

from scripts.board_stats import FIELDS, Stats, parse_stats
from scripts.ddc_board import dump_size, parse_dump, snippet

GROUP_IP = 0xEF01_0101  # 239.1.1.1, docs/protocol.md; the top's default
PORT = 26400
STATS_PORT = 26401  # docs/protocol.md
OWN_IP = 0xC0A8_0A02  # 192.168.10.2, docs/protocol.md
SENDER_IP = 0xC0A8_0164  # mii.udp_frame's default source
SENDER_MAC = bytes.fromhex("02aabbccddee")  # same
SAMPLES = 512  # per datagram, docs/protocol.md
MAC_START_CYCLES = 400  # set in tb/cocotb/run.py
STATS_PERIOD = 20_000  # set in tb/cocotb/run.py (200 us)
LED_ERR = 0b1000


def datagrams() -> list[bytes]:
    raw = snippet(N_SIM).tobytes()
    return [k.to_bytes(8, "big") + raw[2 * SAMPLES * k: 2 * SAMPLES * (k + 1)] for k in range(N_SIM // SAMPLES)]


async def start(dut) -> list[bytes]:
    """Clocks, pins idle, RESET; returns the list the MII TX collector fills."""
    start_soon(Clock(dut.clk100_i, 10, unit="ns").start())
    start_soon(Clock(dut.eth_rx_clk_i, 40, unit="ns").start())
    start_soon(Clock(dut.eth_tx_clk_i, 40, unit="ns").start())
    tx: list[bytes] = []
    start_soon(collect_mii_tx(dut.eth_tx_clk_i, dut.eth_txd_o, dut.eth_tx_en_o, tx))
    dut.btn0_i.value = 0
    dut.eth_rx_dv_i.value = 0
    dut.eth_rxd_i.value = 0
    dut.eth_rxerr_i.value = 0
    await reset(dut)
    return tx


async def reset(dut) -> None:
    """Press RESET, then wait until the MAC is out of reset."""
    dut.ck_rst_n_i.value = 0
    await ClockCycles(dut.clk100_i, 5)
    dut.ck_rst_n_i.value = 1
    await ClockCycles(dut.clk100_i, 10)
    assert dut.eth_rstn_o.value == 0, "PHY must be held in reset right after start-up"
    await ClockCycles(dut.clk100_i, MAC_START_CYCLES + 20)
    assert dut.eth_rstn_o.value == 1, "PHY reset not released"


async def send(dut, payload: bytes, **kw: Any) -> None:
    await send_mii(dut.eth_rx_clk_i, dut.eth_rxd_i, dut.eth_rx_dv_i, udp_frame(payload, GROUP_IP, PORT, **kw))


async def check_dump(dut) -> None:
    exp_i, exp_q = expected_sim()
    got = parse_dump(await uart_bytes(dut.clk100_i, dut.uart_txd_o, dump_size(N_SIM // 4)))
    assert np.array_equal(got[:, 0], exp_i) and np.array_equal(got[:, 1], exp_q), (
        "Ethernet-fed DDC output differs from the bit-true model"
    )


async def next_stats(dut, tx: list[bytes]) -> Stats:
    """Wait for the next stats packet (at most two periods), check its addressing, return it parsed."""
    seen = len(tx)
    for _ in range(2 * STATS_PERIOD + 5000):
        await ClockCycles(dut.clk100_i, 1)
        if len(tx) > seen:
            break
    assert len(tx) > seen, "no stats packet within two periods"
    f = parse_udp_frame(tx[-1])
    assert (f["dst_mac"], f["dst_ip"], f["dport"]) == (SENDER_MAC, SENDER_IP, STATS_PORT), "not sent to the sender"
    assert (f["src_ip"], f["sport"]) == (OWN_IP, PORT)
    return parse_stats(f["payload"])


async def settled_stats(dut, tx: list[bytes]) -> Stats:
    """The second stats packet from now: the first may have started before the last datagram finished."""
    await next_stats(dut, tx)
    return await next_stats(dut, tx)


def check_counts(s: Stats, **want: int) -> None:
    """Every field equals `want` where given, 0 otherwise (rx_fifo_hwm is a level, so only bounded)."""
    for name in FIELDS:
        got = s.fields[name]
        if name == "rx_fifo_hwm":
            assert got <= 2048, f"rx_fifo_hwm {got} exceeds the 2 KB FIFO"
            continue
        assert got == want.get(name, 0), f"stats {name} = {got}, expected {want.get(name, 0)}"


@test(timeout_time=20, timeout_unit="ms")  # no dump (e.g. nothing reached the DDC) fails, not hangs
async def replay_matches_model(dut) -> None:
    """The snippet as four in-order datagrams, twice, with a RESET press between (on the board every eth-check
    starts from a fresh design). Both dumps equal the model and no error is flagged: after the reset the ingest
    must expect seq 0 again, and the DDC and capture must start clean. Nothing is transmitted before the first
    datagram (no destination yet); afterwards stats arrive with exact counts and increasing pkt_seq."""
    tx = await start(dut)
    for _ in range(2):
        await ClockCycles(dut.clk100_i, 2 * STATS_PERIOD)
        assert not tx, "a stats packet went out before any replay datagram arrived"
        for d in datagrams():
            await send(dut, d)
        await check_dump(dut)
        assert int(dut.led_o.value) & LED_ERR == 0, "error LED lit on a clean replay"
        s1 = await next_stats(dut, tx)
        s2 = await next_stats(dut, tx)
        assert s2.pkt_seq == s1.pkt_seq + 1 and s2.uptime - s1.uptime == STATS_PERIOD, "not one packet per period"
        check_counts(s2, ingest_ok=4, eth_ok=4, udp_ok=4, ddc_out=N_SIM // 4)
        await reset(dut)
        tx.clear()


@test(timeout_time=10, timeout_unit="ms")
async def bad_and_foreign_frames_ignored(dut) -> None:
    """Before each datagram, a copy with a bad FCS and a copy to another port. Neither may reach the DDC (the dump
    still equals the model); the bad FCS lights the error LED and counts as eth_crc_err, the other port as
    udp_filtered (not an error)."""
    tx = await start(dut)
    for d in datagrams():
        fake = bytes([d[0]]) + bytes(len(d) - 1)  # same length, wrong samples: visible if it leaks
        await send_mii(dut.eth_rx_clk_i, dut.eth_rxd_i, dut.eth_rx_dv_i,
                       udp_frame(fake, GROUP_IP, PORT, bad_fcs=True))
        await send_mii(dut.eth_rx_clk_i, dut.eth_rxd_i, dut.eth_rx_dv_i, udp_frame(fake, GROUP_IP, PORT + 1))
        await send(dut, d)
    await check_dump(dut)
    assert int(dut.led_o.value) & LED_ERR, "bad-FCS frame did not light the error LED"
    check_counts(await settled_stats(dut, tx), ingest_ok=4, eth_ok=8, eth_crc_err=4, udp_ok=4, udp_filtered=4,
                 ddc_out=N_SIM // 4)


@test(timeout_time=10, timeout_unit="ms")
async def gaps_and_bad_datagrams_counted(dut) -> None:
    """Datagrams 0, 1, then a short one, then 4 (2 and 3 never sent): the ingest counts one bad datagram, one gap
    and two lost; only the three good datagrams' samples reach the DDC (3 x 512 / 4 outputs)."""
    tx = await start(dut)
    ds = datagrams()
    await send(dut, ds[0])
    await send(dut, ds[1])
    await send(dut, ds[2][:-1])  # one byte short
    await send(dut, (4).to_bytes(8, "big") + ds[3][8:])
    check_counts(await settled_stats(dut, tx), ingest_ok=3, ingest_bad=1, ingest_gap=1, ingest_lost=2, eth_ok=4,
                 udp_ok=4, ddc_out=3 * SAMPLES // 4)
    assert int(dut.led_o.value) & LED_ERR, "a gap and a bad datagram did not light the error LED"


@test(timeout_time=20, timeout_unit="ms")
async def corrupt_rx_fifo_restarts_mac_only(dut) -> None:
    """Request 0005 stopgap: an RX FIFO level above its 2,048-byte depth (seen on the board after some link-ups)
    must put the MAC through reset again, without touching the PHY reset (the link must survive), and be counted
    once. Forced for a few cycles (a full FIFO, 2,048, first: legal, no restart), then the replay must still decode
    bit-exact with mac_restarts = 1."""
    tx = await start(dut)
    dut.fifo_level.value = Force(2048)  # exactly full: legal, must not restart anything
    await ClockCycles(dut.clk100_i, 8)
    assert int(dut.mac_rst_q.value) == 0, "a full (2,048-byte) FIFO restarted the MAC"
    dut.fifo_level.value = Force(4095)
    await ClockCycles(dut.clk100_i, 4)
    dut.fifo_level.value = Release()
    await ClockCycles(dut.clk100_i, 4)
    assert int(dut.mac_rst_q.value) == 1, "MAC not put back into reset"
    for _ in range(MAC_START_CYCLES):
        assert int(dut.eth_rstn_o.value) == 1, "PHY reset asserted: the link would drop"
        await ClockCycles(dut.clk100_i, 1)
        if int(dut.mac_rst_q.value) == 0:
            break
    assert int(dut.mac_rst_q.value) == 0, "MAC did not come out of reset again"
    for d in datagrams():
        await send(dut, d)
    await check_dump(dut)
    check_counts(await settled_stats(dut, tx), ingest_ok=4, eth_ok=4, udp_ok=4, ddc_out=N_SIM // 4, mac_restarts=1)
