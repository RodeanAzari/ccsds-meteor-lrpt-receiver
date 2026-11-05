"""End-to-end check of the gs-replay binary over UDP loopback.

What matters for the receiver: every packet arrives with consecutive big-endian sequence
numbers, the IQ bytes concatenate back to exactly the file, a short tail is reported rather
than silently dropped, and real-time pacing actually spreads packets over the right time.

Run: GS_REPLAY=build/gs-Release/gs-replay python -m pytest gs/tests -q
"""

from __future__ import annotations

import os
import socket
import subprocess
import threading
import time
from pathlib import Path

import numpy as np
import pytest

SEQ_BYTES = 8
IQ_BYTES = 1024  # 512 cu8 samples, docs/protocol.md §IQ replay
PACKET_BYTES = SEQ_BYTES + IQ_BYTES
PACKET_S_REALTIME = 512 / 1_024_000  # 500 us

BINARY = Path(os.environ.get("GS_REPLAY", "build/gs-Release/gs-replay"))


@pytest.fixture(scope="module")
def binary() -> Path:
    if not BINARY.is_file():
        pytest.fail(f"{BINARY} not built; run `make gs` first")  # fail, never skip
    return BINARY


def make_file(tmp: Path, packets: int, tail: int, seed: int) -> bytes:
    data = np.random.default_rng(seed).integers(0, 256, packets * IQ_BYTES + tail, dtype=np.uint8).tobytes()
    (tmp / "in.cu8").write_bytes(data)
    return data


def run_and_capture(binary: Path, tmp: Path, extra: list[str]) -> tuple[list[tuple[float, bytes]], str, str, int]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 64 << 20)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(1.0)
    port = sock.getsockname()[1]
    got: list[tuple[float, bytes]] = []

    def rx() -> None:
        while True:
            try:
                d = sock.recv(2048)
            except TimeoutError:
                return
            got.append((time.monotonic(), d))

    t = threading.Thread(target=rx)
    t.start()
    p = subprocess.run(
        [str(binary), str(tmp / "in.cu8"), "--dest", f"127.0.0.1:{port}", *extra],
        capture_output=True,
        text=True,
        timeout=60,
    )
    t.join()
    sock.close()
    return got, p.stdout, p.stderr, p.returncode


def check_stream(got: list[tuple[float, bytes]], data: bytes, packets: int) -> None:
    assert len(got) == packets, f"received {len(got)} of {packets} packets"
    for k, (_, d) in enumerate(got):
        assert len(d) == PACKET_BYTES, f"packet {k}: {len(d)} bytes"
        assert int.from_bytes(d[:SEQ_BYTES], "big") == k, f"packet {k}: sequence out of order"
    payload = b"".join(d[SEQ_BYTES:] for _, d in got)
    assert payload == data[: packets * IQ_BYTES], "IQ bytes altered in transit"


def test_flat_out_delivers_file_bit_exact_and_reports_tail(binary: Path, tmp_path: Path) -> None:
    packets, tail = 2000, 300
    data = make_file(tmp_path, packets, tail, seed=1)
    got, out, err, rc = run_and_capture(binary, tmp_path, ["--flat-out"])
    assert rc == 0, err
    check_stream(got, data, packets)
    assert f"packets={packets}" in out and "target=flat-out" in out
    assert "NOT SENT: final 300 bytes (150 samples)" in err  # loud, not silent


def test_real_time_pacing_spreads_packets(binary: Path, tmp_path: Path) -> None:
    packets = 1000  # 0.5 s of signal at 1.024 MS/s
    data = make_file(tmp_path, packets, 0, seed=2)
    got, out, err, rc = run_and_capture(binary, tmp_path, [])
    assert rc == 0, err
    check_stream(got, data, packets)
    span = got[-1][0] - got[0][0]
    want = (packets - 1) * PACKET_S_REALTIME
    # Lower bound proves pacing; upper bound only catches a gross stall on a busy host.
    assert want * 0.98 <= span <= want * 1.5, f"span {span:.3f} s, want {want:.3f} s"
    assert "target=1.000x" in out


def test_speed_and_count(binary: Path, tmp_path: Path) -> None:
    data = make_file(tmp_path, 400, 0, seed=3)
    got, _out, err, rc = run_and_capture(binary, tmp_path, ["--speed", "4", "--count", "300"])
    assert rc == 0, err
    check_stream(got, data, 300)
    span = got[-1][0] - got[0][0]
    want = 299 * PACKET_S_REALTIME / 4
    assert want * 0.98 <= span <= want * 1.5, f"span {span:.3f} s, want {want:.3f} s"
    assert err == ""  # --count stops early: no tail message


def test_missing_file_fails(binary: Path, tmp_path: Path) -> None:
    p = subprocess.run([str(binary), str(tmp_path / "nope.cu8")], capture_output=True, text=True)
    assert p.returncode != 0 and "cannot open" in p.stderr
