"""The board's output received by the C++ ground station (gs-rx) and compared with SatDump's decode (gs-diff).

    PYTHONPATH=. python scripts/board_gs_rx.py <recording.cu8> <satdump.cadu> --iface <host IP on the cable>
        [--speed X[,Y...]] [--tune HZ] [--bit <bitstream>] [--out DIR]

Per speed, from a freshly programmed board: start gs-rx (DIR/<k>_<speed>x/), set the NCO word to the recording's
coarse estimate (SET_NCO, docs/protocol.md "Control commands"), replay the recording with gs-replay, let gs-rx stop
on --idle, then run gs-diff on its cadus.bin against SatDump's CADU file of the same recording. One row per replay
in board_gs_rx.csv.

gs-rx holds the stats port, so SET_NCO is not confirmed before the replay as board_rx.py does; it is checked after,
from board.nco_word in gs-rx's summary. A replay passes when gs-rx exits 0 with no CADU missing by pkt_seq, nothing
malformed and no ring overflow, the board echoes the NCO word, and every frame both decoders have is bit-identical
(data, ASM and parity) with none that only SatDump has.
"""

from __future__ import annotations

import re
import socket
import subprocess
import sys
import time
from pathlib import Path

from scripts.board_rx import REPLAY_GROUP, REPLAY_PORT, freq_word, set_nco_command
from scripts.ddc_board import GS_REPLAY, wait_for_iface

GS = GS_REPLAY.parent  # make gs
BIT = "build/board/arty_rx_eth_top.bit"
IDLE_S = 10  # gs-rx stops this long after the last CADU packet (stats packets don't count)
SET_NCO_SENDS = 5  # unconfirmed sends, 0.3 s apart: the first may land before the MAC is out of reset
RX_COLS = ["datagrams", "ring_full", "cadu_packets", "cadus_good", "cadus_rs_failed", "cadu_seq_missing",
           "malformed", "rs_symbols_corrected", "stats_packets"]
DIFF_COLS = ["satdump_frames", "common", "only_ours", "only_satdump", "data_bits_differ", "asm_frames_differ",
             "parity_bytes_differ", "result"]


def key_values(text: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in text.split() if "=" in line)


def replay_once(cu8: Path, satdump: Path, iface: str, speed: str, bit: str, word: int,
                out: Path) -> tuple[list[object], bool]:
    subprocess.run(["openFPGALoader", "-b", "arty_a7_100t", bit], capture_output=True, check=True)
    wait_for_iface(iface)
    time.sleep(0.5)  # the MAC leaves reset 200 ms after the link is back
    out.mkdir(parents=True, exist_ok=True)
    rx = subprocess.Popen([str(GS / "gs-rx"), "--out", str(out), "--idle", str(IDLE_S)], stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True)
    try:
        time.sleep(1.0)  # let it bind
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(iface))
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
            for _ in range(SET_NCO_SENDS):
                s.sendto(set_nco_command(word), (REPLAY_GROUP, REPLAY_PORT))
                time.sleep(0.3)
        rp = subprocess.run([str(GS_REPLAY), str(cu8), "--iface", iface, "--speed", speed], capture_output=True,
                            text=True, check=False)
        said = (rp.stdout + rp.stderr).strip()
        print(f"gs-replay exit {rp.returncode}: {said}", flush=True)
        if rp.returncode != 0:
            raise RuntimeError("gs-replay failed")
        stdout, stderr = rx.communicate(timeout=IDLE_S + 60)
    finally:
        if rx.poll() is None:
            rx.kill()
    if rx.returncode != 0:
        raise RuntimeError(f"gs-rx exit {rx.returncode}: {stderr.strip()}")
    summary = key_values(stdout)
    d = subprocess.run([str(GS / "gs-diff"), str(out / "cadus.bin"), str(satdump)], capture_output=True, text=True,
                       check=False)
    if d.returncode == 2:
        raise RuntimeError(f"gs-diff: {d.stderr.strip()}")
    diff = key_values(d.stdout)
    rate = re.search(r"\(([\d.]+)x", said)
    nco_ok = summary.get("board.nco_word") == str(word)
    ok = (all(summary.get(k) == "0" for k in ("cadu_seq_missing", "malformed", "ring_full")) and nco_ok
          and diff.get("result") == "PASS"
          and all(diff.get(k) == "0" for k in DIFF_COLS[3:7]))
    print(f"speed {speed}: " + " ".join(f"{k}={summary.get(k)}" for k in RX_COLS) + f" nco_ok={nco_ok}; gs-diff "
          + " ".join(f"{k}={diff.get(k)}" for k in DIFF_COLS), flush=True)
    row: list[object] = [speed, rate.group(1) if rate else "", *(summary.get(k, "") for k in RX_COLS),
                         summary.get("board.cadus_sent", ""), summary.get("board.fs_slips", ""),
                         summary.get("board.mac_restarts", ""), int(nco_ok), *(diff.get(k, "") for k in DIFF_COLS)]
    return row, ok


def run(cu8: Path, satdump: Path, iface: str, speeds: list[str], tune_hz: float, bit: str, out: Path) -> int:
    from analysis.common import write_result

    word, hz = freq_word(cu8, tune_hz, 2)
    print(f"coarse estimate {hz:.1f} Hz: NCO word 0x{word:08X}", flush=True)
    rows, all_ok = [], True
    for k, speed in enumerate(speeds):
        row, ok = replay_once(cu8, satdump, iface, speed, bit, word, out / f"{k}_{speed}x")
        rows.append(row)
        all_ok &= ok
    write_result(
        "board_gs_rx",
        ["replay_speed", "achieved_speed", *RX_COLS, "board_cadus_sent", "board_fs_slips", "board_mac_restarts",
         "nco_confirmed", *DIFF_COLS],
        rows,
        f"{cu8.name} (make synthetic-iq) streamed by gs-replay to arty_rx_eth_top on the Arty A7-100T, one replay per "
        f"row from a freshly programmed board, received by gs-rx; NCO word 0x{word:08X} (coarse estimate {hz:.1f} Hz) "
        f"by SET_NCO; compared by gs-diff with {satdump} (SatDump 1.2.2's decode of the same recording, "
        "satdump_crosscheck.csv row 1)",
        command=f"PYTHONPATH=. python scripts/board_gs_rx.py {cu8} {satdump} --iface {iface} --speed "
        f"{','.join(speeds)} --tune {tune_hz:g} --bit {bit}",
    )
    return 0 if all_ok else 1


def main(argv: list[str]) -> int:
    if len(argv) >= 2:
        opts = dict(zip(argv[2::2], argv[3::2], strict=False))
        if "--iface" in opts and set(opts) <= {"--iface", "--speed", "--tune", "--bit", "--out"}:
            return run(Path(argv[0]), Path(argv[1]), opts["--iface"], opts.get("--speed", "1").split(","),
                       float(opts.get("--tune", 150_000)), opts.get("--bit", BIT),
                       Path(opts.get("--out", "build/board_gs_rx")))
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
