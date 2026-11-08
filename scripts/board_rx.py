"""The whole receiver on the board (rtl/top/arty_rx_eth_top.sv): build parameters and the replay check.

    PYTHONPATH=. python scripts/board_rx.py freq-word <recording.cu8> [--tune HZ] [--seconds S]
        print the DDC NCO word for the recording: the host's coarse estimate (ADR 0002) over its first S seconds
        (default 2), around the tuning offset HZ (default 150000), as BOARD_GENERICS for `make board`
    PYTHONPATH=. python scripts/board_rx.py check <recording.cu8> <truth.cadu> --iface <host IP on the cable>
        [--speed X[,Y...]] [--bit <bitstream>]
        reprogram the board (with --bit), replay the recording with gs-replay, receive the CADU packets
        (docs/protocol.md type 2) and stats (type 1), and compare each CADU's 892 data bytes with the truth file
        (signal-spec.md: the bytes SatDump's output is compared on); one replay and result row per speed in
        board_rx_eth.csv

`parse_cadu` is the reference parser for type 2 packets.
"""

from __future__ import annotations

import re
import struct
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from model import ddc_fixed, sync_fixed
from model.receiver import RxConfig
from scripts.board_stats import HDR, StatsListener
from scripts.ddc_board import GS_REPLAY, wait_for_iface

TYPE_CADU = 2
VERSION = 1
CADU_BYTES = 1024
N_PAYLOAD = 8 + CADU_BYTES  # docs/protocol.md "CADU": header field n
DATA = slice(4, 4 + 892)  # signal-spec.md: compare the data bytes
QUIET_S = 3.0  # no new CADU packet for this long after the replay ends: done
MAC_START_WAIT_S = 0.5  # after the link is back, the MAC leaves reset 200 ms after programming


@dataclass(frozen=True)
class Cadu:
    pkt_seq: int
    uptime: int
    alternate: bool
    swap: bool
    flywheel: bool
    asm_errors: int
    corrections: tuple[int, ...]  # per codeword 0..3: symbols corrected, -1 = uncorrectable
    data: bytes


def parse_cadu(pkt: bytes) -> Cadu:
    """Raises ValueError on anything that is not a well-formed version-1 CADU packet."""
    if len(pkt) < HDR.size:
        raise ValueError(f"short packet: {len(pkt)} bytes")
    ptype, version, n, pkt_seq, uptime = HDR.unpack_from(pkt)
    if ptype != TYPE_CADU:
        raise ValueError(f"type {ptype}, not CADU")
    if version != VERSION:
        raise ValueError(f"version {version}, expected {VERSION}")
    if n != N_PAYLOAD or len(pkt) != HDR.size + n:
        raise ValueError(f"{len(pkt)} bytes for n = {n} (expected n = {N_PAYLOAD}, {HDR.size + N_PAYLOAD} bytes)")
    flags, asm, *rs = struct.unpack_from(">6B", pkt, HDR.size)
    if flags & 0xF8 or asm > 32 or any(r & 0x60 or (r & 0x80 and r & 0x1F) or (r & 0x1F) > 16 for r in rs):
        raise ValueError(f"reserved bits or out-of-range status: flags {flags:#x}, asm {asm}, rs {rs}")
    if pkt[HDR.size + 6: HDR.size + 8] != b"\0\0":
        raise ValueError("reserved bytes 6-7 not zero")
    return Cadu(pkt_seq, uptime, bool(flags & 1), bool(flags & 2), bool(flags & 4), asm,
                tuple(-1 if r & 0x80 else r for r in rs), pkt[HDR.size + 8:])


def freq_word(cu8: Path, tune_hz: float, seconds: float) -> tuple[int, float]:
    cfg = RxConfig(tune_offset_hz=tune_hz)
    n = 2 * int(seconds * cfg.fs)
    raw = np.fromfile(cu8, dtype=np.uint8, count=n)
    hz = sync_fixed.coarse_tune_hz(raw[: raw.size // 2 * 2], cfg)
    return ddc_fixed.freq_word(hz, cfg.fs), hz


STAT_COLS = ["ingest_ok", "ingest_gap", "ingest_lost", "ingest_late", "eth_ovf_lost", "cadus_sent", "fs_slips",
             "fs_dropped", "mac_restarts"]


@dataclass
class Replay:
    cadus: list[Cadu]
    malformed: list[str]
    stats: dict[str, int]  # the last stats packet's fields, empty if none arrived
    said: str  # gs-replay's report


def replay(cu8: Path, iface: str, speed: str, bit: str | None) -> Replay:
    """One replay from a fresh board (reprogrammed with `bit`): every CADU packet in arrival order, and the
    counters after the last one."""
    cadus: list[Cadu] = []
    bad: list[str] = []

    def on_packet(data: bytes) -> None:
        try:
            cadus.append(parse_cadu(data))
        except ValueError as e:
            bad.append(str(e))

    listener = StatsListener(other=on_packet)
    try:
        if bit is not None:
            subprocess.run(["openFPGALoader", "-b", "arty_a7_100t", bit], capture_output=True, check=True)
            wait_for_iface(iface)
        time.sleep(MAC_START_WAIT_S)
        r = subprocess.run([str(GS_REPLAY), str(cu8), "--iface", iface, "--speed", speed], capture_output=True,
                           text=True, check=False)
        said = (r.stdout + r.stderr).strip()
        print(f"gs-replay exit {r.returncode}: {said}", flush=True)
        if r.returncode != 0:
            raise RuntimeError("gs-replay failed")
        seen, quiet_since = len(cadus), time.monotonic()
        while time.monotonic() - quiet_since < QUIET_S:  # the last frames leave the chain after the replay
            time.sleep(0.1)
            if len(cadus) != seen:
                seen, quiet_since = len(cadus), time.monotonic()
        st = listener.latest
        st = listener.wait_newer(st.pkt_seq if st is not None else -1, 1.0)
    finally:
        listener.close()
    return Replay(cadus, bad, st.fields if st is not None else {}, said)


def replay_once(cu8: Path, truth: set[bytes], iface: str, speed: str, bit: str | None) -> tuple[list[object], bool]:
    """One replay from a fresh board: its result row, and whether every CADU matched."""
    rp = replay(cu8, iface, speed, bit)
    cadus, bad, fields = rp.cadus, rp.malformed, rp.stats
    seqs = [c.pkt_seq for c in cadus]
    missing = (max(seqs) + 1 - len(set(seqs))) if seqs else 0
    match = sum(c.data[DATA] in truth for c in cadus)
    rs = [x for c in cadus for x in c.corrections]
    rate = re.search(r"\(([\d.]+)x", rp.said)
    print(f"speed {speed}: {len(cadus)} CADU packets ({missing} missing by pkt_seq, {len(bad)} malformed); {match} "
          f"match the truth on the data bytes; RS: {sum(max(x, 0) for x in rs)} symbols corrected, {rs.count(-1)} "
          "codewords failed", flush=True)
    print("stats: " + " ".join(f"{k}={v}" for k, v in fields.items()) if fields else "no stats packet", flush=True)
    row: list[object] = [speed, rate.group(1) if rate else "", len(cadus), missing, len(bad), match, len(truth),
                         sum(max(x, 0) for x in rs), rs.count(-1), *(fields.get(k, "") for k in STAT_COLS)]
    return row, bool(cadus) and match == len(cadus) and not missing and not bad


def check(cu8: Path, truth_path: Path, iface: str, speeds: list[str], bit: str | None) -> int:
    """One replay per speed, each from a fresh board; one result row per replay."""
    from analysis.common import write_result

    truth_raw = truth_path.read_bytes()
    truth = {truth_raw[i: i + CADU_BYTES][DATA] for i in range(0, len(truth_raw), CADU_BYTES)}
    rows, all_ok = [], True
    for speed in speeds:
        row, ok = replay_once(cu8, truth, iface, speed, bit)
        rows.append(row)
        all_ok &= ok
    write_result(
        "board_rx_eth",
        ["replay_speed", "achieved_speed", "cadu_packets", "missing_by_seq", "malformed", "matching_truth",
         "truth_frames", "rs_symbols_corrected", "rs_codewords_failed", *STAT_COLS],
        rows,
        f"{cu8.name} (make synthetic-iq, or a recording in data/MANIFEST.md) streamed by gs-replay over 100 Mb/s "
        f"Ethernet to arty_rx_eth_top on the Arty A7-100T, one replay per row, each from a freshly programmed board; "
        f"truth {truth_path.name}",
        command=f"PYTHONPATH=. python scripts/board_rx.py check {cu8} {truth_path} --iface {iface} "
        f"--speed {','.join(speeds)}" + (f" --bit {bit}" if bit else ""),
    )
    return 0 if all_ok else 1


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "freq-word":
        opts = dict(zip(argv[2::2], argv[3::2], strict=False))
        word, hz = freq_word(Path(argv[1]), float(opts.get("--tune", 150_000)), float(opts.get("--seconds", 2)))
        print(f"# coarse estimate {hz:.1f} Hz", file=sys.stderr)
        print(f"FREQ_WORD=32'h{word:08X}")
        return 0
    if len(argv) >= 3 and argv[0] == "check":
        opts = dict(zip(argv[3::2], argv[4::2], strict=False))
        if "--iface" not in opts:
            print("check needs --iface <host IP on the cable to the Arty>", file=sys.stderr)
            return 2
        return check(Path(argv[1]), Path(argv[2]), opts["--iface"], opts.get("--speed", "1").split(","),
                     opts.get("--bit"))
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
