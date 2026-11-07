"""arty_ddc_rom_top: the whole bring-up design (ROM -> DDC -> capture -> UART), checked through its UART pin.

Why it matters: on the board the only evidence is the bytes on the serial line. This test decodes that line
exactly as the host will and compares every DDC output with the bit-true model, so a failure on hardware points at
the board (clock, pins, UART link), not at the design. parse_dump also checks the dump's CRC-32 trailer.
It runs a short snippet with a fast UART to stay quick, keeps
the top's default NCO word (a wrong default would fail here), and presses BTN0 to check the repeat dump matches.
"""

from __future__ import annotations

from cocotb import start_soon, test
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge
from ddc_board import N_SIM, expected_sim, uart_bytes

from scripts.ddc_board import dump_size, parse_dump


@test()
async def dump_matches_model_and_repeats(dut) -> None:
    start_soon(Clock(dut.clk100_i, 10, unit="ns").start())
    dut.btn0_i.value = 0
    dut.ck_rst_n_i.value = 0
    await ClockCycles(dut.clk100_i, 5)
    dut.ck_rst_n_i.value = 1

    n_out = N_SIM // 4
    exp_i, exp_q = expected_sim()
    first = parse_dump(await uart_bytes(dut.clk100_i, dut.uart_txd_o, dump_size(n_out)))
    assert first[:, 0].tolist() == exp_i.tolist() and first[:, 1].tolist() == exp_q.tolist(), (
        "board-path output differs from the bit-true model"
    )
    assert int(dut.led_o.value) & 0b0110 == 0b0110, "LD5 (snippet played) and LD6 (capture full) should be on"

    for _ in range(20):
        await RisingEdge(dut.clk100_i)
    dut.btn0_i.value = 1  # held: one rising edge, one repeat dump
    second = parse_dump(await uart_bytes(dut.clk100_i, dut.uart_txd_o, dump_size(n_out)))
    dut.btn0_i.value = 0
    assert (second == first).all(), "repeat dump differs from the first"
