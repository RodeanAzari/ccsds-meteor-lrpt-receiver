"""The board's output received by the C++ ground station (gs-rx) and compared with SatDump's decode (gs-diff).

    PYTHONPATH=. python scripts/board_gs_rx.py <recording.cu8> <satdump.cadu> --iface <host IP on the cable>
        [--speed X[,Y...]] [--tune HZ] [--bit <bitstream>] [--out DIR] [--idle S] [--recording NAME]
        [--truth <truth.cadu> <truth.packets>]

Per speed, from a freshly programmed board: start gs-rx (DIR/<k>_<speed>x/), set the NCO word to the recording's
coarse estimate (SET_NCO, docs/protocol.md "Control commands"), replay the recording with gs-replay, let gs-rx stop
on --idle, then run gs-diff on its cadus.bin against SatDump's CADU file of the same recording. One row per replay
in board_gs_rx.csv.

gs-rx holds the stats port, so SET_NCO is not confirmed before the replay as board_rx.py does; it is checked after,
from board.nco_word in gs-rx's summary. A replay passes when gs-rx exits 0 with no CADU missing by pkt_seq, nothing
malformed and no ring overflow, the board echoes the NCO word, and every frame both decoders have is bit-identical
(data, ASM and parity) with none that only SatDump has.

With --truth (a recording that carries space packets, make_synthetic_iq.py --packets), the replay also checks
gs-rx's packets.bin: it must equal the golden model's demux of the truth CADUs the board delivered (so only packets
touching a lost frame may be missing), and scripts/packet_diff.py against SatDump must pass. Rows then go to
board_gs_rx_packets.csv instead.

With --recording NAME (a cut of a real pass, NAME its data/MANIFEST.md row), rows go to board_gs_rx_real.csv and
a replay passes on gs-rx's checks, the NCO echo and gs-diff's own verdict (common frames, data bytes equal): frames
only one decoder has, and ASM/parity bytes (SatDump leaves channel errors there, signal-spec.md), are counted, not
failed. A real pass fades, so raise --idle above the longest gap between CADUs at the replay speed.
"""

from __future__ import annotations

import re
import socket
import subprocess
import sys
import time
from pathlib import Path

from model.space_packets import demux
from scripts.board_rx import REPLAY_GROUP, REPLAY_PORT, freq_word, set_nco_command
from scripts.ddc_board import GS_REPLAY, wait_for_iface
from scripts.packet_diff import InputError, compare, split_cadus, split_packets

GS = GS_REPLAY.parent  # make gs
BIT = "build/board/arty_rx_eth_top.bit"
IDLE_S = 10  # gs-rx stops this long after the last CADU packet (stats packets don't count)
SET_NCO_SENDS = 5  # unconfirmed sends, 0.3 s apart: the first may land before the MAC is out of reset
RX_COLS = ["datagrams", "ring_full", "cadu_packets", "cadus_good", "cadus_rs_failed", "cadu_seq_missing",
           "malformed", "rs_symbols_corrected", "stats_packets"]
DIFF_COLS = ["satdump_frames", "common", "only_ours", "only_satdump", "data_bits_differ", "asm_frames_differ",
             "parity_bytes_differ", "result"]
PACKET_COLS = ["packets", "truth_packets", "expected_packets", "packets_exact", "pd_satdump", "pd_equal", "pd_differ",
               "pd_only_ours", "pd_only_satdump", "pd_explained", "pd_unexplained", "pd_result"]


def tx_dropped(ip: str) -> int:
    """The host interface's kernel TX drop counter: replay datagrams that never reached the wire."""
    out = subprocess.run(["ip", "-4", "-o", "addr"], capture_output=True, text=True, check=True).stdout
    names = [line.split()[1] for line in out.splitlines() if f"inet {ip}/" in line]
    if len(names) != 1:
        raise RuntimeError(f"no single interface has {ip}: {names}")
    return int(Path(f"/sys/class/net/{names[0]}/statistics/tx_dropped").read_text())


def key_values(text: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in text.split() if "=" in line)


def packet_check(out: Path, satdump: Path, truth: tuple[Path, Path]) -> tuple[list[object], bool]:
    """gs-rx's packets against the truth (exactly) and against SatDump (packet_diff), PACKET_COLS."""
    ours_cadus = split_cadus((out / "cadus.bin").read_bytes(), "ours")
    ours = split_packets((out / "packets.bin").read_bytes())
    truth_cadus = split_cadus(truth[0].read_bytes(), "truth")
    got = {c[4:896] for c in ours_cadus}  # signal-spec.md: the 892 data bytes
    expected, _ = demux(c for c in truth_cadus if c[4:896] in got)
    exact = ours == expected
    row: list[object] = [len(ours), len(split_packets(truth[1].read_bytes())), len(expected), int(exact)]
    try:
        d = compare(ours_cadus, ours, split_cadus(satdump.read_bytes(), "satdump"))
    except InputError as e:  # a packet of ours that is not in our own CADUs: recorded as a failed replay
        row += [""] * 7 + [f"ERROR {e}"]
        print(f"packets: {row}", flush=True)
        return row, False
    explained = ";".join(f"{k}:{v}" for k, v in sorted(d.explained.items()))
    row += [d.satdump, d.equal, d.differ, d.only_ours, d.only_satdump, explained, len(d.unexplained),
            "PASS" if d.passed else "FAIL"]
    print("packets: " + " ".join(f"{k}={v}" for k, v in zip(PACKET_COLS, row, strict=True)), flush=True)
    return row, exact and d.passed and len(ours) > 0


def replay_passed(summary: dict[str, str], diff: dict[str, str], nco_ok: bool, real: bool) -> bool:
    """gs-rx lost, malformed or overflowed nothing, the board echoed the NCO word, and every common frame's data
    bytes equal SatDump's; for a synthetic recording also no frame only SatDump has and no ASM or parity byte
    differs (the channel is clean enough that both decoders see every frame error-free)."""
    return (all(summary.get(k) == "0" for k in ("cadu_seq_missing", "malformed", "ring_full")) and nco_ok
            and diff.get("result") == "PASS"
            and (real or all(diff.get(k) == "0" for k in DIFF_COLS[3:7])))


def replay_once(cu8: Path, satdump: Path, iface: str, speed: str, bit: str, word: int,
                out: Path, truth: tuple[Path, Path] | None = None, idle: float = IDLE_S,
                real: bool = False) -> tuple[list[object], bool]:
    subprocess.run(["openFPGALoader", "-b", "arty_a7_100t", bit], capture_output=True, check=True)
    wait_for_iface(iface)
    time.sleep(0.5)  # the MAC leaves reset 200 ms after the link is back
    out.mkdir(parents=True, exist_ok=True)
    rx = subprocess.Popen([str(GS / "gs-rx"), "--out", str(out), "--idle", f"{idle:g}"], stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True)
    try:
        time.sleep(1.0)  # let it bind
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(iface))
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
            for _ in range(SET_NCO_SENDS):
                s.sendto(set_nco_command(word), (REPLAY_GROUP, REPLAY_PORT))
                time.sleep(0.3)
        dropped0 = tx_dropped(iface)
        rp = subprocess.run([str(GS_REPLAY), str(cu8), "--iface", iface, "--speed", speed], capture_output=True,
                            text=True, check=False)
        dropped = tx_dropped(iface) - dropped0
        said = (rp.stdout + rp.stderr).strip()
        print(f"gs-replay exit {rp.returncode}: {said}", flush=True)
        if rp.returncode != 0:
            raise RuntimeError("gs-replay failed")
        stdout, stderr = rx.communicate(timeout=idle + 60)
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
    ok = replay_passed(summary, diff, nco_ok, real)
    print(f"speed {speed}: host_tx_dropped={dropped} " + " ".join(f"{k}={summary.get(k)}" for k in RX_COLS)
          + f" nco_ok={nco_ok}; gs-diff "
          + " ".join(f"{k}={diff.get(k)}" for k in DIFF_COLS), flush=True)
    row: list[object] = [speed, rate.group(1) if rate else "", dropped, *(summary.get(k, "") for k in RX_COLS),
                         summary.get("board.ingest_lost", ""), summary.get("board.cadus_sent", ""),
                         summary.get("board.fs_slips", ""),
                         summary.get("board.mac_restarts", ""), int(nco_ok), *(diff.get(k, "") for k in DIFF_COLS)]
    if truth:
        prow, pok = packet_check(out, satdump, truth)
        row += prow
        ok &= pok
    return row, ok


def run(cu8: Path, satdump: Path, iface: str, speeds: list[str], tune_hz: float, bit: str, out: Path,
        truth: tuple[Path, Path] | None = None, idle: float = IDLE_S, recording: str | None = None) -> int:
    from analysis.common import write_result

    word, hz = freq_word(cu8, tune_hz, 2)
    print(f"coarse estimate {hz:.1f} Hz: NCO word 0x{word:08X}", flush=True)
    rows, all_ok = [], True
    for k, speed in enumerate(speeds):
        row, ok = replay_once(cu8, satdump, iface, speed, bit, word, out / f"{k}_{speed}x", truth, idle,
                              recording is not None)
        rows.append(row)
        all_ok &= ok
    source = ("make_synthetic_iq.py --packets; truth " + ", ".join(t.name for t in truth)) if truth \
        else f"a cut of {recording}" if recording else "make synthetic-iq"
    write_result(
        "board_gs_rx_packets" if truth else "board_gs_rx_real" if recording else "board_gs_rx",
        ["replay_speed", "achieved_speed", "host_tx_dropped", *RX_COLS, "board_ingest_lost", "board_cadus_sent",
         "board_fs_slips", "board_mac_restarts",
         "nco_confirmed", *DIFF_COLS, *(PACKET_COLS if truth else [])],
        rows,
        f"{cu8.name} ({source}) streamed by gs-replay to arty_rx_eth_top on the Arty A7-100T, one replay per "
        f"row from a freshly programmed board, received by gs-rx; NCO word 0x{word:08X} (coarse estimate {hz:.1f} Hz) "
        f"by SET_NCO; compared by gs-diff with {satdump} (SatDump 1.2.2's decode of the same recording"
        + ("" if truth or recording else ", satdump_crosscheck.csv row 1") + ")",
        command=f"PYTHONPATH=. python scripts/board_gs_rx.py {cu8} {satdump} --iface {iface} --speed "
        f"{','.join(speeds)} --tune {tune_hz:g} --bit {bit} --idle {idle:g}"
        + (f" --recording {recording}" if recording else "") + (f" --truth {truth[0]} {truth[1]}" if truth else ""),
        recording=recording,
    )
    return 0 if all_ok else 1


def main(argv: list[str]) -> int:
    truth = None
    if "--truth" in argv and len(argv) > argv.index("--truth") + 2:
        k = argv.index("--truth")
        truth = (Path(argv[k + 1]), Path(argv[k + 2]))
        argv = argv[:k] + argv[k + 3:]
    if len(argv) >= 2:
        opts = dict(zip(argv[2::2], argv[3::2], strict=False))
        if "--iface" in opts and set(opts) <= {"--iface", "--speed", "--tune", "--bit", "--out", "--idle",
                                               "--recording"}:
            return run(Path(argv[0]), Path(argv[1]), opts["--iface"], opts.get("--speed", "1").split(","),
                       float(opts.get("--tune", 150_000)), opts.get("--bit", BIT),
                       Path(opts.get("--out", "build/board_gs_rx")), truth, float(opts.get("--idle", IDLE_S)),
                       opts.get("--recording"))
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
