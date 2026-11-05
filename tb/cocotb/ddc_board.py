"""Shared between tb/cocotb/run.py (writes the ROM before the build) and the board-top test."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import numpy.typing as npt

from scripts.ddc_board import expected, write_rom

N_SIM = 2048  # short snippet: 512 outputs, enough for every pipeline and both dumps


def rom_path(build_dir: Path) -> Path:
    return build_dir / "iq_rom_sim.mem"


def prepare(build_dir: Path) -> None:
    write_rom(rom_path(build_dir), N_SIM)


def expected_sim() -> tuple[npt.NDArray[np.int64], npt.NDArray[np.int64]]:
    return expected(N_SIM)
