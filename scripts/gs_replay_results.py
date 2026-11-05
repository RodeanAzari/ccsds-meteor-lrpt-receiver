#!/usr/bin/env python3
"""Measure gs-replay over UDP loopback on a whole recording: real time and flat out.

For each run: packets received vs. sent, sequence errors, whether the received IQ is
byte-identical to the file, and the achieved rate gs-replay logs. Writes data/results/gs_replay_loopback.csv
(sidecar from analysis/interpretations/). Loopback says nothing about the Ethernet link to the Arty; it shows the
host side paces correctly and loses nothing on its own.

Run: PYTHONPATH=. python scripts/gs_replay_results.py [RECORDING.cu8]
"""

from __future__ import annotations

import hashlib
import re
import socket
import subprocess
import sys
import threading
from pathlib import Path

BINARY = Path("build/gs-Release/gs-replay")
DEFAULT_IN = Path("data/synthetic/synthetic_seed2026_1024000SPS.cu8")
SEQ_BYTES, IQ_BYTES = 8, 1024


def run(recording: Path, mode: list[str]) -> dict[str, str]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 64 << 20)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(2.0)
    port = sock.getsockname()[1]
    h = hashlib.sha256()
    stats = {"rx": 0, "seq_err": 0}

    def rx() -> None:
        expect = 0
        while True:
            try:
                d = sock.recv(2048)
            except TimeoutError:
                return
            if int.from_bytes(d[:SEQ_BYTES], "big") != expect:
                stats["seq_err"] += 1
            expect = int.from_bytes(d[:SEQ_BYTES], "big") + 1
            h.update(d[SEQ_BYTES:])
            stats["rx"] += 1

    t = threading.Thread(target=rx)
    t.start()
    p = subprocess.run(
        [str(BINARY), str(recording), "--dest", f"127.0.0.1:{port}", *mode], capture_output=True, text=True
    )
    t.join()
    sock.close()
    if p.returncode != 0:
        sys.exit(f"gs-replay failed: {p.stderr}")
    log = dict(re.findall(r"(\w+)=(\S+)", p.stdout))
    sent = int(log["packets"])
    with recording.open("rb") as f:
        want = hashlib.sha256(f.read(sent * IQ_BYTES)).hexdigest()
    return {
        "mode": log["target"],
        "packets_sent": str(sent),
        "packets_received": str(stats["rx"]),
        "seq_errors": str(stats["seq_err"]),
        "payload_bit_exact": str(h.hexdigest() == want),
        "elapsed_s": re.search(r"elapsed=(\S+) s", p.stdout).group(1),  # type: ignore[union-attr]
        "achieved_sps": log["rate"],
        "x_real_time": re.search(r"\(([\d.]+)x real time", p.stdout).group(1),  # type: ignore[union-attr]
        "late_packets": log["late"],
        "tail_not_sent": p.stderr.strip() or "none",
    }


def main() -> None:
    recording = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_IN
    if not recording.is_file():
        sys.exit(f"{recording} missing; run `make synthetic-iq` first")
    rows = [run(recording, []), run(recording, ["--speed", "5"]), run(recording, ["--flat-out"])]
    from analysis.common import write_result

    gxx = subprocess.run(["g++", "--version"], capture_output=True, text=True).stdout.splitlines()[0]
    write_result(
        "gs_replay_loopback",
        ["recording", *rows[0].keys()],
        [[recording.name, *r.values()] for r in rows],
        f"recording {recording} (make synthetic-iq, seed 2026), replayed over UDP loopback",
        command=f"PYTHONPATH=. python scripts/gs_replay_results.py {recording}",
        tools=f"{gxx}, gs-replay Release build",
    )


if __name__ == "__main__":
    main()
