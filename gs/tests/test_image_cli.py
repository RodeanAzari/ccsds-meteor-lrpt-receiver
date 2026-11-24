"""The gs-image binary: its PNGs, report and exit code, on the committed MSU-MR vectors (gs/tests/data/msumr).

Why it matters: gs-image's PNGs are the deliverable image. msumr_test.cpp checks the decoder's pixels against the
golden model; this checks they reach the file intact (a PNG any reader opens, the right size, the right pixels, one per
channel with data, named as SatDump names them), and the exit code a script relies on: 0 with images, 1 with none,
2 on input it cannot read or that ends in a partial packet.

Run: GS_IMAGE=build/gs-Release/gs-image python -m pytest gs/tests -q
"""

from __future__ import annotations

import os
import struct
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

BINARY = Path(os.environ.get("GS_IMAGE", "build/gs-Release/gs-image"))
VECTORS = Path("gs/tests/data/msumr")
WIDTH = 1568


@pytest.fixture(scope="module")
def binary() -> Path:
    if not BINARY.is_file():
        pytest.fail(f"{BINARY} not built; run `make gs` first")  # fail, never skip
    return BINARY


def run(binary: Path, packets: Path, out: Path) -> tuple[int, dict[str, str], str]:
    r = subprocess.run([str(binary), str(packets), str(out)], capture_output=True, text=True, timeout=60)
    return r.returncode, dict(line.split("=", 1) for line in r.stdout.split()), r.stderr


def expected(name: str) -> list[np.ndarray]:
    b, pos, out = (VECTORS / f"{name}.image").read_bytes(), 0, []
    for _ in range(6):
        (rows,) = struct.unpack_from("<I", b, pos)
        out.append(np.frombuffer(b, np.uint8, rows * WIDTH, pos + 4).reshape(rows, WIDTH))
        pos += 4 + rows * WIDTH
    return out


@pytest.mark.parametrize("name", ["real", "corrupt", "tie"])
def test_pngs_hold_the_model_pixels(binary: Path, tmp_path: Path, name: str) -> None:
    code, kv, _ = run(binary, VECTORS / f"{name}.packets", tmp_path)
    assert code == 0
    for ch, want in enumerate(expected(name), start=1):
        f = tmp_path / f"MSU-MR-{ch}.png"
        assert kv[f"ch{ch}_rows"] == str(want.shape[0])
        if want.shape[0] == 0:
            assert not f.exists(), f"channel {ch} has no data but a PNG was written"
            continue
        img = Image.open(f)
        assert img.mode == "L"
        assert np.array_equal(np.array(img), want), f"{name} channel {ch}"
    summary = (VECTORS / f"{name}.summary").read_text().split()
    assert [kv[f"ch{ch}_segments"] for ch in range(1, 7)] == summary[3::4]


def test_no_msumr_data_exits_1(binary: Path, tmp_path: Path) -> None:
    (tmp_path / "p.bin").write_bytes(bytes([0x00, 0x46, 0xC0, 0x01, 0x00, 0x00, 0x00]))  # one telemetry packet
    code, kv, _ = run(binary, tmp_path / "p.bin", tmp_path / "out")
    assert code == 1 and kv["packets"] == "1"
    assert not list((tmp_path / "out").glob("*.png"))


def test_partial_packet_exits_2(binary: Path, tmp_path: Path) -> None:
    whole = (VECTORS / "real.packets").read_bytes()
    (tmp_path / "p.bin").write_bytes(whole[:-1])
    code, _, err = run(binary, tmp_path / "p.bin", tmp_path / "out")
    assert code == 2 and "partial packet" in err


def test_bad_arguments_exit_2(binary: Path, tmp_path: Path) -> None:
    assert subprocess.run([str(binary)], capture_output=True, timeout=10).returncode == 2
    assert run(binary, tmp_path / "missing.bin", tmp_path)[0] == 2
