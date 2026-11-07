"""Shared between tb/cocotb/run.py (writes the ROM before the build) and the board-top tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
from cocotb.triggers import ClockCycles, FallingEdge

from scripts.ddc_board import expected, write_rom

N_SIM = 2048  # short snippet: 512 outputs, enough for every pipeline and both dumps
CLKS_PER_BIT = 8  # board tops' UART in simulation, set in tb/cocotb/run.py


def rom_path(build_dir: Path) -> Path:
    return build_dir / "iq_rom_sim.mem"


def prepare(build_dir: Path) -> None:
    write_rom(rom_path(build_dir), N_SIM)


def expected_sim() -> tuple[npt.NDArray[np.int64], npt.NDArray[np.int64]]:
    return expected(N_SIM)


async def uart_bytes(clk: Any, txd: Any, n: int) -> bytes:
    """Receive n 8N1 bytes from a top's UART pin, sampling at bit centres."""
    out = bytearray()
    while len(out) < n:
        await FallingEdge(txd)
        await ClockCycles(clk, CLKS_PER_BIT // 2)
        assert txd.value == 0, "start bit glitch"
        b = 0
        for k in range(8):
            await ClockCycles(clk, CLKS_PER_BIT)
            b |= int(txd.value) << k
        await ClockCycles(clk, CLKS_PER_BIT)
        assert txd.value == 1, f"framing error on byte {len(out)}"
        out.append(b)
    return bytes(out)
