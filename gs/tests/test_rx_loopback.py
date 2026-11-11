"""End to end: board packets over UDP loopback into the gs-rx binary, its files and summary checked against the models.

Why it matters: this is the path a pass takes after the board (buildplan §4): datagrams -> ring -> parsers -> RS
gate -> demultiplexer -> files. The packets are built by docs/protocol.md's layout (types 1, 2) around CADUs from
model/space_packets.py `mux`; the expected CADUs and space packets come from the models (`demux` over the CADUs that
pass the RS gate, as SatDump's rs_usecheck would), not from gs-rx. One CADU is marked uncorrectable, one CADU packet
is never sent (a pkt_seq gap), and a stats packet and a malformed datagram are mixed in: each must land in its own
counter, and nothing else may change.

Run: GS_RX=build/gs-Release/gs-rx python -m pytest gs/tests -q
"""

from __future__ import annotations

import os
import random
import socket
import struct
import subprocess
import time
from pathlib import Path

import pytest

from model.space_packets import demux, mux, space_packet
from scripts.board_stats import FIELDS
from scripts.packet_diff import compare, split_cadus, split_packets

BINARY = Path(os.environ.get("GS_RX", "build/gs-Release/gs-rx"))
DIFF = Path(os.environ.get("GS_DIFF", "build/gs-Release/gs-diff"))
VIEW = Path(os.environ.get("GS_VIEW", "build/gs-Release/gs-view"))
HDR = struct.Struct(">BBHIQ")


@pytest.fixture(scope="module")
def binary() -> Path:
    if not BINARY.is_file():
        pytest.fail(f"{BINARY} not built; run `make gs` first")  # fail, never skip
    return BINARY


def cadu_packet(seq: int, cadu: bytes, rs: tuple[int, int, int, int] = (0, 3, 0, 1)) -> bytes:
    """docs/protocol.md "CADU": header, flags, asm_errors, rs[0..3], 2 reserved, the CADU."""
    return HDR.pack(2, 1, 1032, seq, 1000 * seq) + bytes([0, seq % 5, *rs, 0, 0]) + cadu


def stats_packet(seq: int, values: list[int]) -> bytes:
    return HDR.pack(1, 2, len(values), seq, 77) + struct.pack(f">{len(values)}I", *values)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_board_packets_to_cadus_and_space_packets(binary: Path, tmp_path: Path) -> None:
    rng = random.Random(42)
    pkts = [space_packet(rng.randrange(2047), k, rng.randbytes(rng.randint(1, 2500))) for k in range(80)]
    cadus = mux(pkts, first_counter=1000)
    assert len(cadus) > 40
    rs_failed, never_sent = 20, 30  # CADU indices
    good = [c for k, c in enumerate(cadus) if k not in (rs_failed, never_sent)]
    want_packets, want_counts = demux(good)
    assert want_counts.gaps == 2 and want_counts.dropped_gap >= 1  # the test exercises the drops

    datagrams = []
    for k, c in enumerate(cadus):
        if k == never_sent:
            continue
        datagrams.append(cadu_packet(k, c, (0, 0x80, 0, 0) if k == rs_failed else (0, 3, 0, 1)))
        if k == 5:
            datagrams.append(stats_packet(0, list(range(100, 100 + len(FIELDS)))))
        if k == 6:
            datagrams.append(b"\x02\x01junk")  # CADU-typed, 6 bytes: malformed

    port = free_port()
    out = tmp_path / "rx"
    proc = subprocess.Popen([str(binary), "--out", str(out), "--port", str(port), "--idle", "2.5"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        time.sleep(0.3)  # let it bind
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as tx:
            for d in datagrams:
                tx.sendto(d, ("127.0.0.1", port))
                time.sleep(0.0005)  # loopback stays lossless at this rate; gs-rx would count ring_full anyway
        # While gs-rx waits out --idle, its snapshot (every 0.5 s) must show it running with every datagram counted.
        live: dict[str, str] = {}
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and live.get("datagrams") != str(len(datagrams)):
            time.sleep(0.05)
            if (out / "status.txt").exists():
                live = dict(line.split("=", 1) for line in (out / "status.txt").read_text().split())
        assert live.get("state") == "running" and live.get("datagrams") == str(len(datagrams)), live
        stdout, stderr = proc.communicate(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 0, stderr
    summary = dict(line.split("=", 1) for line in stdout.split())
    assert (out / "gs-rx.txt").read_text() == stdout

    assert (out / "cadus.bin").read_bytes() == b"".join(good)
    assert (out / "packets.bin").read_bytes() == b"".join(want_packets)
    want = {
        "datagrams": len(datagrams), "ring_full": 0, "cadu_packets": len(cadus) - 1, "cadus_good": len(good),
        "cadus_rs_failed": 1, "cadu_seq_missing": 1, "cadu_seq_late": 0, "stats_packets": 1, "malformed": 1,
        "demux_cadus": want_counts.cadus, "demux_other_vcid": 0, "demux_gaps": want_counts.gaps,
        "packets": want_counts.packets, "dropped_gap": want_counts.dropped_gap,
        "dropped_length": want_counts.dropped_length, "bad_pointer": 0, "dropped_pointer": 0,
        # rs = (0, 3, 0, 1): 4 symbols per CADU that decoded; the failed one (0, 0x80, 0, 0) corrected none.
        "rs_symbols_corrected": 4 * len(good),
        "asm_bit_errors": sum(k % 5 for k in range(len(cadus)) if k != never_sent),
        "status_write_errors": 0,
    }
    for k, v in want.items():
        assert int(summary[k]) == v, f"{k} = {summary[k]}, want {v}"
    assert int(summary["board.ingest_ok"]) == 100 and int(summary["board.ctrl_bad"]) == 100 + len(FIELDS) - 1

    # The live status (ADR 0016) ends final, with the same counters as the summary; gs-view draws it.
    status = dict(line.split("=", 1) for line in (out / "status.txt").read_text().split())
    assert status.pop("state") == "final" and int(status.pop("elapsed_ms")) > 0
    assert status == summary
    assert not (out / "status.txt.tmp").exists()
    r = subprocess.run([str(VIEW), str(out), "--once"], capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, r.stderr
    assert "[final]" in r.stdout and f"received {len(cadus) - 1}" in r.stdout and "\x1b" not in r.stdout
    assert f"FER {100 / (len(cadus) - 1):.3f} %" in r.stdout

    # The comparison tools on gs-rx's own files, against a decode that has every CADU (as SatDump might): the two
    # CADUs gs-rx lacks are listed, not failed, and so are the packets they hold.
    satdump = tmp_path / "satdump.cadu"
    satdump.write_bytes(b"".join(cadus))
    r = subprocess.run([str(DIFF), str(out / "cadus.bin"), str(satdump)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stdout + r.stderr
    d = dict(line.split("=", 1) for line in r.stdout.split())
    assert (d["common"], d["only_ours"], d["only_satdump_first"]) == (str(len(good)), "0", "5/1020,5/1030")
    p = compare(split_cadus((out / "cadus.bin").read_bytes(), "ours"),
                split_packets((out / "packets.bin").read_bytes()), cadus)
    assert p.passed and p.unexplained == []
    assert p.equal + p.explained["satdump_tail"] == len(want_packets)  # SatDump holds back the stream's last one
    assert p.only_satdump == p.explained["missing_in_ours"] + p.explained["our_drop"] >= 2


def test_view_without_status_or_with_bad_arguments(tmp_path: Path) -> None:
    r = subprocess.run([str(VIEW), str(tmp_path), "--once"], capture_output=True, text=True, timeout=10)
    assert r.returncode == 1 and "cannot read" in r.stderr
    for args in ([], [str(tmp_path), "--bogus"], [str(tmp_path), "--once", "x"]):
        assert subprocess.run([str(VIEW), *args], capture_output=True, timeout=10).returncode == 2, args


def test_bad_arguments_fail_loudly(binary: Path) -> None:
    for args in ([], ["--out"], ["--out", "x", "--port", "70000"], ["--out", "x", "--idle", "0"], ["--bogus", "1"]):
        r = subprocess.run([str(binary), *args], capture_output=True, text=True, timeout=10)
        assert r.returncode == 2 and "usage" in r.stderr, args
