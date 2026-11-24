"""A recorded pass through the board for a demo (photo or video): no result CSV, no comparison.

    PYTHONPATH=. python scripts/demo_replay.py <recording.cu8> --iface <host IP on the cable>
        [--speed X] [--out DIR] [--idle S]

Programs the board, starts gs-rx (--out DIR, default build/demo), sets the NCO word to the recording's coarse
estimate (SET_NCO), replays the recording with gs-replay at --speed (default 1, real time), waits for gs-rx to
stop on --idle (default 60 s: a real pass fades), then runs gs-image on gs-rx's packets.bin into DIR/images.
Watch it live in a second terminal with `build/gs-Release/gs-view DIR`. The same steps as one replay of
scripts/board_gs_rx.py; measured runs go through that script, not this one. Exit 0 when gs-rx and gs-image both
succeed.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

from scripts.board_gs_rx import BIT, GS, SET_NCO_SENDS
from scripts.board_rx import REPLAY_GROUP, REPLAY_PORT, freq_word, set_nco_command
from scripts.ddc_board import GS_REPLAY, wait_for_iface

TUNE_HZ = 150_000  # data/MANIFEST.md: the signal is +150 kHz from the tuned frequency


def run(cu8: Path, iface: str, speed: str, out: Path, idle: float) -> int:
    word, hz = freq_word(cu8, TUNE_HZ, 2)
    print(f"coarse estimate {hz:.1f} Hz: NCO word 0x{word:08X}", flush=True)
    subprocess.run(["openFPGALoader", "-b", "arty_a7_100t", BIT], capture_output=True, check=True)
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
        print(f"replaying {cu8.name} at {speed}x; gs-view {out} shows it live", flush=True)
        rp = subprocess.run([str(GS_REPLAY), str(cu8), "--iface", iface, "--speed", speed], check=False)
        if rp.returncode != 0:
            print(f"gs-replay exit {rp.returncode}", file=sys.stderr)
            return 1
        stdout, stderr = rx.communicate(timeout=idle + 60)
    finally:
        if rx.poll() is None:
            rx.kill()
    print(stdout, end="", flush=True)
    if rx.returncode != 0:
        print(f"gs-rx exit {rx.returncode}: {stderr.strip()}", file=sys.stderr)
        return 1
    img = subprocess.run([str(GS / "gs-image"), str(out / "packets.bin"), str(out / "images")], check=False)
    return 0 if img.returncode == 0 else 1


def main(argv: list[str]) -> int:
    if argv:
        opts = dict(zip(argv[1::2], argv[2::2], strict=False))
        if "--iface" in opts and set(opts) <= {"--iface", "--speed", "--out", "--idle"}:
            return run(Path(argv[0]), opts["--iface"], opts.get("--speed", "1"), Path(opts.get("--out", "build/demo")),
                       float(opts.get("--idle", 60)))
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
