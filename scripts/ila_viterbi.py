"""Viterbi path metrics captured on the board by the ILA, checked step by step against the bit-true model.

    PYTHONPATH=. python scripts/ila_viterbi.py replay <iface> <recording.cu8> [--tune HZ]   # syn/ila_capture_acs.tcl
    PYTHONPATH=. python scripts/ila_viterbi.py check <ila.csv> <recording.cu8>

The ILA build of arty_rx_eth_top (`make board BOARD_TOP=arty_rx_eth_top ILA=1`, syn/impl_board.tcl) stores one entry
per ACS step: storage is qualified on the clock enable of fec_acs_array's path-metric registers, which is the input
handshake. Each entry holds, sampled in the handshake cycle (probe order):
    probe0  pm_q, all 64 path metrics before the step (576 bits, state s at bits 9s..9s+8)
    probe1  s_tdata, the step's two 4-bit soft symbols {b, a} (a = G1 in bits 3:0)
    probe2  m_tdata, the decisions registered by the previous step (64 bits, bit s = state s)
    probe3  the step enable (must be 1 in every stored entry)
The metrics never reset between frames, so no reference run can line up with them; instead each step is checked on
its own: model.viterbi_fixed.acs_step() from entry k's metrics and symbols must give entry k+1's metrics and
decisions exactly. A wrong branch metric, a swapped symbol, a wrong predecessor, a wrong modulo compare or a lost or
repeated step breaks that.

`replay` is what the capture Tcl runs once the ILA is armed: wait for the link, SET_NCO from the recording's coarse
estimate, replay it once at 1x. `check` writes data/results/viterbi_board_ila.csv and, for the plot, the first
PLOT_STEPS steps' metrics relative to the best state (viterbi_board_ila_pm.csv).
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import numpy.typing as npt

from model.viterbi_fixed import acs_step

SOFT_BITS, PM_BITS, N_STATES = 4, 9, 64  # fec_acs_array parameters in arty_rx_eth_top (ADRs 0005, 0006)
PLOT_STEPS = 200

Ints = npt.NDArray[np.int64]


def parse_acs_ila(text: str) -> tuple[Ints, Ints, Ints, npt.NDArray[np.bool_]]:
    """Vivado ILA CSV -> (pm (n, 64), a (n,), b (n,), decisions (n, 64)), buffer order. Raises unless the window
    starts at the trigger and every stored entry is a step (enable 1), i.e. the capture conditions really applied."""
    lines = text.strip().splitlines()
    if len(lines) < 3 or not lines[1].startswith("Radix"):
        raise ValueError("not a Vivado ILA CSV")
    rows = [line.split(",") for line in lines[2:]]
    if len(rows[0]) != 7:
        raise ValueError(f"expected 3 columns + 4 probes, got {len(rows[0])} columns")
    if int(rows[0][2]) != 1 or int(rows[0][1]) != 0:
        raise ValueError("ILA window does not start at the trigger")
    if any(int(r[6], 16) != 1 for r in rows):
        raise ValueError("ILA stored an entry that was not an ACS step")
    pm_words = [int(r[3], 16) for r in rows]
    mask = (1 << PM_BITS) - 1
    pm = np.array([[(w >> (PM_BITS * s)) & mask for s in range(N_STATES)] for w in pm_words], dtype=np.int64)
    sym = np.array([int(r[4], 16) for r in rows], dtype=np.int64)
    dec_words = [int(r[5], 16) for r in rows]
    dec = np.array([[(w >> s) & 1 for s in range(N_STATES)] for w in dec_words], dtype=bool)
    return pm, sym & 0xF, sym >> SOFT_BITS, dec


def check_steps(pm: Ints, a: Ints, b: Ints, dec: npt.NDArray[np.bool_]) -> tuple[int, int, int]:
    """(steps whose next metrics differ from the model's, steps whose decisions differ, first such step or -1)."""
    choose1, nxt = acs_step(pm[:-1], a[:-1, np.newaxis], b[:-1, np.newaxis], SOFT_BITS, PM_BITS)
    bad_pm = (nxt != pm[1:]).any(axis=1)
    bad_dec = (choose1 != dec[1:]).any(axis=1)
    bad = np.flatnonzero(bad_pm | bad_dec)
    return int(bad_pm.sum()), int(bad_dec.sum()), int(bad[0]) if bad.size else -1


def relative_metrics(pm: Ints) -> Ints:
    """Each step's metrics minus the best one, unwrapped by the RTL's modulo compare against state 0."""
    half, mask = 1 << (PM_BITS - 1), (1 << PM_BITS) - 1
    rel = ((pm - pm[:, :1] + half) & mask) - half
    out: Ints = rel - rel.min(axis=1, keepdims=True)
    return out


def check(csv_path: Path, recording: Path) -> int:
    from analysis.common import write_result

    pm, a, b, dec = parse_acs_ila(csv_path.read_text())
    n = len(pm)
    bad_pm, bad_dec, first = check_steps(pm, a, b, dec)
    rel = relative_metrics(pm)
    print(f"{n} ACS steps captured, {n - 1} checked: {bad_pm} metric mismatches, {bad_dec} decision mismatches"
          f" (first {first}); spread up to {int(rel.max())}", flush=True)
    cmd = f"PYTHONPATH=. python scripts/ila_viterbi.py check {csv_path} {recording}"
    source = (f"{recording.name} replayed once at 1x by gs-replay to the ILA build of arty_rx_eth_top on the Arty "
              f"A7-100T (syn/ila_capture_acs.tcl), NCO word by SET_NCO from the coarse estimate; the ILA triggers on "
              f"the first ACS step after arming and stores one entry per step")
    write_result("viterbi_board_ila",
                 ["steps_captured", "steps_checked", "metric_mismatches", "decision_mismatches", "first_mismatch",
                  "max_spread", "pm_bits", "soft_bits", "clk_mhz"],
                 [[n, n - 1, bad_pm, bad_dec, first, int(rel.max()), PM_BITS, SOFT_BITS, 100]], source, command=cmd,
                 recording=str(recording))
    write_result("viterbi_board_ila_pm", ["step", "a", "b", *(f"s{s}" for s in range(N_STATES))],
                 [[k, int(a[k]), int(b[k]), *map(int, rel[k])] for k in range(min(PLOT_STEPS, n))], source,
                 command=cmd, recording=str(recording))
    return 0 if bad_pm == bad_dec == 0 and n > 1 else 1


def replay(iface: str, recording: Path, tune_hz: float) -> int:
    from scripts.board_rx import REPLAY_GROUP, REPLAY_PORT, freq_word, set_nco_command
    from scripts.ddc_board import GS_REPLAY, wait_for_iface

    word, hz = freq_word(recording, tune_hz, 2)
    wait_for_iface(iface)
    time.sleep(0.5)  # the MAC leaves reset 200 ms after the link is back
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(iface))
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        for _ in range(5):  # unconfirmed, as in board_gs_rx.py: the first may land before the MAC is out of reset
            s.sendto(set_nco_command(word), (REPLAY_GROUP, REPLAY_PORT))
            time.sleep(0.3)
    rp = subprocess.run([str(GS_REPLAY), str(recording), "--iface", iface, "--speed", "1"], capture_output=True,
                        text=True, check=False)
    print(f"coarse estimate {hz:.1f} Hz, NCO word 0x{word:08X}; gs-replay exit {rp.returncode}: "
          f"{(rp.stdout + rp.stderr).strip()}", flush=True)
    return rp.returncode


def main(argv: list[str]) -> int:
    if argv[:1] == ["check"] and len(argv) == 3:
        return check(Path(argv[1]), Path(argv[2]))
    if argv[:1] == ["replay"] and len(argv) in (3, 5) and (len(argv) == 3 or argv[3] == "--tune"):
        return replay(argv[1], Path(argv[2]), float(argv[4]) if len(argv) == 5 else 150_000.0)
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
