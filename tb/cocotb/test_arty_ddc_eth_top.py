"""arty_ddc_eth_top: the Ethernet-fed board design, from the PHY's MII pins to the UART pin.

Why it matters: on the board the evidence is the bytes on the serial line after gs-replay streams the snippet.
This test sends the same snippet as replay datagrams (docs/protocol.md), built here from the RFCs and the protocol
doc, as MII nibbles at 25 MHz, then decodes the UART dump exactly as scripts/ddc_board.py will and compares every
DDC output with the bit-true model. A failure on hardware then points at the board or the link, not the design.
It also covers the top's own wiring: the multicast group and port the defaults select, the PHY reset released
after start-up, and that frames which must not reach the DDC (bad FCS, another
port) don't, while the sticky error LED records the bad frame.
The MMCM stand-in passes clk100 through, so the core runs at 100 MHz here as on the board.
"""

from __future__ import annotations

import numpy as np
from cocotb import start_soon, test
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles
from ddc_board import N_SIM, expected_sim, uart_bytes
from mii import send_mii, udp_frame

from scripts.ddc_board import dump_size, parse_dump, snippet

GROUP_IP = 0xEF01_0101  # 239.1.1.1, docs/protocol.md; the top's default
PORT = 26400
SAMPLES = 512  # per datagram, docs/protocol.md
MAC_START_CYCLES = 400  # set in tb/cocotb/run.py
LED_ERR = 0b1000


def datagrams() -> list[bytes]:
    raw = snippet(N_SIM).tobytes()
    return [k.to_bytes(8, "big") + raw[2 * SAMPLES * k: 2 * SAMPLES * (k + 1)] for k in range(N_SIM // SAMPLES)]


async def start(dut) -> None:
    start_soon(Clock(dut.clk100_i, 10, unit="ns").start())
    start_soon(Clock(dut.eth_rx_clk_i, 40, unit="ns").start())
    dut.btn0_i.value = 0
    dut.eth_rx_dv_i.value = 0
    dut.eth_rxd_i.value = 0
    dut.eth_rxerr_i.value = 0
    await reset(dut)


async def reset(dut) -> None:
    """Press RESET, then wait until the MAC is out of reset."""
    dut.ck_rst_n_i.value = 0
    await ClockCycles(dut.clk100_i, 5)
    dut.ck_rst_n_i.value = 1
    await ClockCycles(dut.clk100_i, 10)
    assert dut.eth_rstn_o.value == 0, "PHY must be held in reset right after start-up"
    await ClockCycles(dut.clk100_i, MAC_START_CYCLES + 20)
    assert dut.eth_rstn_o.value == 1, "PHY reset not released"


async def check_dump(dut) -> None:
    exp_i, exp_q = expected_sim()
    got = parse_dump(await uart_bytes(dut.clk100_i, dut.uart_txd_o, dump_size(N_SIM // 4)))
    assert np.array_equal(got[:, 0], exp_i) and np.array_equal(got[:, 1], exp_q), (
        "Ethernet-fed DDC output differs from the bit-true model"
    )


@test(timeout_time=20, timeout_unit="ms")  # no dump (e.g. nothing reached the DDC) fails, not hangs
async def replay_matches_model(dut) -> None:
    """The snippet as four in-order datagrams, twice, with a RESET press between (on the board every eth-check
    starts with one: opening the serial port). Both dumps equal the model and no error is flagged: after the reset
    the ingest must expect seq 0 again, and the DDC and capture must start clean."""
    await start(dut)
    for _ in range(2):
        for d in datagrams():
            await send_mii(dut.eth_rx_clk_i, dut.eth_rxd_i, dut.eth_rx_dv_i, udp_frame(d, GROUP_IP, PORT))
        await check_dump(dut)
        assert int(dut.led_o.value) & LED_ERR == 0, "error LED lit on a clean replay"
        await reset(dut)


@test(timeout_time=10, timeout_unit="ms")  # no dump (e.g. nothing reached the DDC) fails, not hangs
async def bad_and_foreign_frames_ignored(dut) -> None:
    """Before each datagram, a copy with a bad FCS and a copy to another port. Neither may reach the DDC (the dump
    still equals the model); the bad FCS lights the error LED, the other port doesn't count as an error."""
    await start(dut)
    for d in datagrams():
        fake = bytes([d[0]]) + bytes(len(d) - 1)  # same length, wrong samples: visible if it leaks
        await send_mii(dut.eth_rx_clk_i, dut.eth_rxd_i, dut.eth_rx_dv_i,
                       udp_frame(fake, GROUP_IP, PORT, bad_fcs=True))
        await send_mii(dut.eth_rx_clk_i, dut.eth_rxd_i, dut.eth_rx_dv_i, udp_frame(fake, GROUP_IP, PORT + 1))
        await send_mii(dut.eth_rx_clk_i, dut.eth_rxd_i, dut.eth_rx_dv_i, udp_frame(d, GROUP_IP, PORT))
    await check_dump(dut)
    assert int(dut.led_o.value) & LED_ERR, "bad-FCS frame did not light the error LED"

