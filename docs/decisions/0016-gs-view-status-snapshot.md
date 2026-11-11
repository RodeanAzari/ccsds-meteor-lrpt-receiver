# 0016: gs-view reads a status snapshot that gs-rx writes

## Context

`gs-view` (buildplan §4) is the live terminal view of a replay: sync state, frame and packet counts, FER,
corrections, and later a constellation. Everything it shows arrives in the board's packets on UDP port 26401
(`docs/protocol.md`), and `gs-rx` already receives, parses and counts them. One UDP socket gets each datagram (a
second listener on the port would split the stream or need `SO_REUSEPORT` multicast tricks the board's unicast
reply doesn't support).

## Options considered

| Option | Effect |
|---|---|
| **gs-rx writes a snapshot (key=value file, every 0.5 s, atomic rename); gs-view reads and draws it** | gs-rx stays the only receiver and does no terminal work; gs-view is a plain reader, testable on a file; the snapshot can be watched or scripted (`cat`, `watch`) without gs-view |
| gs-view built into gs-rx (`--view`) | No file, but terminal drawing in the receiver process, and the view dies with the receiver's output redirected |
| gs-view also listens on the port | Two receivers of one unicast stream: not possible without splitting it |

## Decision

The user chose the snapshot (2026-11-10). `gs-rx --out DIR` writes `DIR/status.txt` every 0.5 s: the same key=value
lines as its final summary (one formatter, `gs/status.hpp`, into a fixed buffer: no allocation on the data path),
plus `state` (`running`, then `final`), `elapsed_ms` and `status_write_errors`. Written to `status.txt.tmp` and renamed, so a reader never
sees half a file. `gs-view DIR` redraws from it every 0.5 s (ANSI clear and home, no curses dependency); rates come
from two successive snapshots. `--once` prints one frame without control codes and exits (tests, scripts).

Shown: board sync (`fs_locked`), slips and dropped peaks, NCO word, MAC restarts; datagrams and the ingest's gap,
lost and late counts, ring overflows, malformed packets; CADUs received, good, RS-failed and missing by pkt_seq,
FER after RS (RS-failed / CADU packets), CADU rate; RS symbols corrected and ASM bit errors; the demultiplexer's
counters (ADR 0015).

Not shown in v1, and the screen says so: the live constellation (needs a soft-symbol debug tap in the RTL and a
packet type for it: later, after the first real decode) and Viterbi corrections (the board does not report them;
RS corrections are the channel errors left after Viterbi).

## Consequences

- One more file in gs-rx's output directory; its contents are a superset of `gs-rx.txt` while running.
- The view lags the receiver by up to 1 s; fine for a human watching a 15-minute pass.

## Measured evidence

- `gs/tests/status_test.cpp`, `gs/tests/view_test.cpp`, `gs/tests/test_rx_loopback.py` (gs-view `--once` on the
  live status of a loopback run).
