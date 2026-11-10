"""End-to-end check of the gs-replay binary over UDP loopback.

What matters for the receiver: every packet arrives with consecutive big-endian sequence
numbers, the IQ bytes concatenate back to exactly the file, a short tail is reported rather
than silently dropped, and real-time pacing actually spreads packets over the right time.

Run: GS_REPLAY=build/gs-Release/gs-replay python -m pytest gs/tests -q
"""

from __future__ import annotations

import os
import socket
import struct
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
# Pacing is checked by what the pacer guarantees: packet k is never sent before its deadline D_k = k x period after
# the schedule starts, which is after the process is launched. So every packet must arrive at least D_k after launch.
# Lateness (a loaded host) can never fail that; sending early (unpaced, or a wrong speed factor) always does. The old
# check, first-to-last span >= 98% of the ideal, flaked both ways under load: the receiver thread woke late on the
# first packet (CI run 42148010432), and gs-replay itself is preempted before its first sendto and then catches up
# (span 3-5 ms short at 4x, load average ~45, 2026-11-10); and with flat-out sending its span reached 1.02x the ideal,
# so it could pass an unpaced sender. Arrival times are the kernel's (SO_TIMESTAMPNS, CLOCK_REALTIME, stamped as the
# datagram reaches the socket), not this thread's wake-up.
CLOCK_SLACK_S = 0.5e-3  # gs-replay sleeps on CLOCK_MONOTONIC; NTP may slew REALTIME by 500 ppm (0.25 ms over 0.5 s)
# Upper bound on the span, only against a grossly slow pacer (e.g. --speed ignored: 4x the ideal at 4x). A stall is
# a fixed time, not a fraction: 22 ms (1.6x the 37 ms ideal at 4x) seen at load average ~42.
STALL_FACTOR = 1.1
STALL_S = 0.05
SO_TIMESTAMPNS = 35  # Linux asm-generic/socket.h (also SCM_TIMESTAMPNS); Python's socket module does not export it
TIMESPEC = struct.Struct("@qq")  # struct timespec on 64-bit Linux

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


Capture = tuple[list[tuple[float, bytes]], str, str, int, float]


def run_and_capture(binary: Path, tmp: Path, extra: list[str]) -> Capture:
    """Packets received (kernel time, bytes), stdout, stderr, exit code, and the launch time (CLOCK_REALTIME, taken
    before the process starts, so before its pacing schedule does)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 64 << 20)
    sock.setsockopt(socket.SOL_SOCKET, SO_TIMESTAMPNS, 1)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(1.0)
    port = sock.getsockname()[1]
    got: list[tuple[float, bytes]] = []

    def rx() -> None:
        while True:
            try:
                d, anc, _, _ = sock.recvmsg(2048, socket.CMSG_SPACE(TIMESPEC.size))
            except TimeoutError:
                return
            stamps = [c for lvl, typ, c in anc if lvl == socket.SOL_SOCKET and typ == SO_TIMESTAMPNS]
            if len(stamps) != 1:  # never fall back to the thread's own clock: that is the flakiness removed
                got.append((float("nan"), d))
                continue
            sec, nsec = TIMESPEC.unpack(stamps[0][: TIMESPEC.size])
            got.append((sec + nsec * 1e-9, d))

    t = threading.Thread(target=rx)
    t.start()
    launched = time.time()
    p = subprocess.run(
        [str(binary), str(tmp / "in.cu8"), "--dest", f"127.0.0.1:{port}", *extra],
        capture_output=True,
        text=True,
        timeout=60,
    )
    t.join()
    sock.close()
    return got, p.stdout, p.stderr, p.returncode, launched


def check_paced(by_seq: list[tuple[float, bytes]], launched: float, period_s: float) -> None:
    """Packets in sequence order: none before its deadline after launch; the whole run not grossly slow."""
    lead = [k * period_s - (t - launched) for k, (t, _) in enumerate(by_seq)]
    worst = max(range(len(lead)), key=lead.__getitem__)
    assert lead[worst] <= CLOCK_SLACK_S, (
        f"packet {worst} arrived {lead[worst] * 1e3:.2f} ms before its deadline: not paced at {period_s * 1e6:.1f} us")
    times = [t for t, _ in by_seq]
    span, want = max(times) - min(times), (len(by_seq) - 1) * period_s
    assert span <= want * STALL_FACTOR + STALL_S, f"span {span:.3f} s, want {want:.3f} s"


def check_stream(got: list[tuple[float, bytes]], data: bytes, packets: int) -> list[tuple[float, bytes]]:
    """Every sequence number 0..packets-1 exactly once, each with its slice of the file. Returns the packets in
    sequence order. Arrival order is the kernel's: loopback reorders under load (the sender migrates between CPUs,
    each with its own receive backlog; 2 runs in 20 at load average ~42), which gs-replay cannot prevent."""
    assert len(got) == packets, f"received {len(got)} of {packets} packets"
    assert all(t == t for t, _ in got), "a datagram arrived without its kernel timestamp (SO_TIMESTAMPNS)"
    for k, (_, d) in enumerate(got):
        assert len(d) == PACKET_BYTES, f"packet {k}: {len(d)} bytes"
    by_seq = sorted(got, key=lambda g: int.from_bytes(g[1][:SEQ_BYTES], "big"))
    seqs = [int.from_bytes(d[:SEQ_BYTES], "big") for _, d in by_seq]
    assert seqs == list(range(packets)), "sequence numbers missing, repeated or not counted from 0"
    payload = b"".join(d[SEQ_BYTES:] for _, d in by_seq)
    assert payload == data[: packets * IQ_BYTES], "IQ bytes altered in transit"
    return by_seq


def test_flat_out_delivers_file_bit_exact_and_reports_tail(binary: Path, tmp_path: Path) -> None:
    packets, tail = 2000, 300
    data = make_file(tmp_path, packets, tail, seed=1)
    got, out, err, rc, _ = run_and_capture(binary, tmp_path, ["--flat-out"])
    assert rc == 0, err
    check_stream(got, data, packets)
    assert f"packets={packets}" in out and "target=flat-out" in out
    assert "NOT SENT: final 300 bytes (150 samples)" in err  # loud, not silent


def test_real_time_pacing_spreads_packets(binary: Path, tmp_path: Path) -> None:
    packets = 1000  # 0.5 s of signal at 1.024 MS/s
    data = make_file(tmp_path, packets, 0, seed=2)
    got, out, err, rc, launched = run_and_capture(binary, tmp_path, [])
    assert rc == 0, err
    check_paced(check_stream(got, data, packets), launched, PACKET_S_REALTIME)
    assert "target=1.000x" in out


def test_speed_and_count(binary: Path, tmp_path: Path) -> None:
    data = make_file(tmp_path, 400, 0, seed=3)
    got, _out, err, rc, launched = run_and_capture(binary, tmp_path, ["--speed", "4", "--count", "300"])
    assert rc == 0, err
    check_paced(check_stream(got, data, 300), launched, PACKET_S_REALTIME / 4)
    assert err == ""  # --count stops early: no tail message


def test_missing_file_fails(binary: Path, tmp_path: Path) -> None:
    p = subprocess.run([str(binary), str(tmp_path / "nope.cu8")], capture_output=True, text=True)
    assert p.returncode != 0 and "cannot open" in p.stderr
