"""The gs-diff binary: its exit code and report, on CADU files built by model/space_packets.py `mux`.

Why it matters: gs-diff's exit code is what a real-pass run (buildplan §8.5) or a script checks. It must be 0 when
the data bytes of every common frame agree, even with the ASM and parity errors SatDump leaves in its .cadu and with
frames only one side has; 1 on any data difference or when nothing was compared; 2 on input it cannot read. The
comparison logic itself is tested in cadu_diff_test.cpp.

Run: GS_DIFF=build/gs-Release/gs-diff python -m pytest gs/tests -q
"""

from __future__ import annotations

import os
import random
import subprocess
from pathlib import Path

import pytest

from model.space_packets import mux, space_packet

BINARY = Path(os.environ.get("GS_DIFF", "build/gs-Release/gs-diff"))


@pytest.fixture(scope="module")
def binary() -> Path:
    if not BINARY.is_file():
        pytest.fail(f"{BINARY} not built; run `make gs` first")  # fail, never skip
    return BINARY


@pytest.fixture(scope="module")
def cadus() -> list[bytes]:
    rng = random.Random(7)
    out = mux([space_packet(rng.randrange(2047), k, rng.randbytes(rng.randint(1, 900))) for k in range(40)],
              first_counter=500)
    assert len(out) >= 10
    return out


def run(binary: Path, tmp: Path, ours: list[bytes], ref: list[bytes] | bytes,
        *extra: str) -> tuple[int, dict[str, str]]:
    (tmp / "ours.bin").write_bytes(b"".join(ours))
    (tmp / "ref.cadu").write_bytes(ref if isinstance(ref, bytes) else b"".join(ref))
    r = subprocess.run([str(binary), str(tmp / "ours.bin"), str(tmp / "ref.cadu"), *extra],
                       capture_output=True, text=True, timeout=30)
    return r.returncode, dict(line.split("=", 1) for line in r.stdout.split())


def flip(c: bytes, i: int, mask: int) -> bytes:
    b = bytearray(c)
    b[i] ^= mask
    return bytes(b)


def test_satdump_like_file_passes(binary: Path, cadus: list[bytes], tmp_path: Path) -> None:
    # SatDump's side: ASM and parity errors as received, one frame it missed, one we missed, its own order kept.
    ref = [flip(c, 1, 0x10) if k % 3 == 0 else flip(c, 1000, 0x01) if k % 3 == 1 else c
           for k, c in enumerate(cadus) if k != 2]
    ours = [c for k, c in enumerate(cadus) if k != 6]
    code, s = run(binary, tmp_path, ours, ref)
    assert code == 0, s
    assert s["result"] == "PASS" and s["first_divergence"] == "-"
    assert int(s["common"]) == len(cadus) - 2
    assert s["only_ours_first"] == "5/502" and s["only_satdump_first"] == "5/506"
    assert int(s["asm_frames_differ"]) == sum(1 for k in range(len(cadus)) if k % 3 == 0 and k not in (2, 6))
    assert int(s["parity_bytes_differ"]) == sum(1 for k in range(len(cadus)) if k % 3 == 1 and k not in (2, 6))


def test_data_difference_fails_with_its_location(binary: Path, cadus: list[bytes], tmp_path: Path) -> None:
    ref = list(cadus)
    ref[4] = flip(ref[4], 300, 0x20)
    code, s = run(binary, tmp_path, cadus, ref)
    assert code == 1 and s["result"] == "FAIL"
    assert s["first_divergence"] == "5/504,ours_frame:4,satdump_frame:4,byte:300,bit:2"
    assert (s["data_frames_differ"], s["data_bytes_differ"], s["data_bits_differ"]) == ("1", "1", "1")


def test_nothing_in_common_fails(binary: Path, cadus: list[bytes], tmp_path: Path) -> None:
    code, s = run(binary, tmp_path, cadus[:3], cadus[3:])
    assert code == 1 and s["common"] == "0" and s["result"] == "FAIL"


def test_bad_input_and_arguments_exit_2(binary: Path, cadus: list[bytes], tmp_path: Path) -> None:
    code, _ = run(binary, tmp_path, cadus, b"".join(cadus)[:-1])  # not whole CADUs
    assert code == 2
    code, _ = run(binary, tmp_path, cadus + cadus[:1], cadus)  # a key twice
    assert code == 2
    for args in ([], [str(tmp_path / "ours.bin")], [str(tmp_path / "missing"), str(tmp_path / "ours.bin")],
                 [str(tmp_path / "ours.bin")] * 2 + ["--list", "x"], [str(tmp_path / "ours.bin")] * 2 + ["--bogus"]):
        r = subprocess.run([str(binary), *args], capture_output=True, text=True, timeout=10)
        assert r.returncode == 2, args


def test_list_limits_the_keys_shown(binary: Path, cadus: list[bytes], tmp_path: Path) -> None:
    code, s = run(binary, tmp_path, cadus, cadus[:2], "--list", "2")
    assert code == 0 and s["only_ours_first"] == "5/502,5/503" and int(s["only_ours"]) == len(cadus) - 2
