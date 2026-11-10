# 0014: Control commands on the replay port; runtime NCO word

## Context

The DDC NCO word carries the host's coarse frequency estimate (ADR 0002). Until now it was a build parameter of
`arty_rx_eth_top`, so every recording needed its own bitstream (a full Vivado run per real pass), and the
BER campaign tied to one word baked into both of its builds. Real passes (Phase E, then F) each have their own
offset. Buildplan §3.1 asks for control commands from the host over UDP. The only one needed now is the NCO word.

Constraints:
- fpga-eth-core's `udp_rx` (`eth-core-v0.2`) accepts one destination port (`cfg_port_i`). P3 cannot edit it.
- Every sample of a replay must see the same word, or no model run reproduces the decode (bit-exact checks, BER).
- eth-core has no ARP and no reliable transport: a command can be lost or arrive out of order with the replay.

## Options considered

| Option | Cost | Effect |
|---|---|---|
| **In-band on the replay port: byte 0 bit 7 set marks a command** | `ctrl_rx` (snoops the stream), 3 lines in the ingest | One port, no eth-core change. Replay `seq` is a u64 counted from 0, so bit 63 is never set in replay data (2⁶³ datagrams) |
| Second port: a second `udp_rx`, or a request to P2 for a port mask | A broadcast of eth_rx's stream to two `udp_rx` (both must stall it), or a new eth-core tag | Cleaner separation, but a request and a wait for one command, or duplicated parsing logic |
| Commands over UART | UART RX block, host serial handling | The serial port sometimes resets the design (CLAUDE.md §12); two links for one replay |
| Keep the build parameter | None | One build per recording; the BER campaign and real passes stay slow |

When a word takes effect:

| Option | Effect |
|---|---|
| **Accept only before the DDC's first sample since the MAC left reset; refuse and count afterwards** | Every sample of a replay sees one word. The host reprograms or resets the board before each replay anyway |
| Accept at any time | A command that overtakes or trails replay datagrams retunes mid-replay at a point that depends on host timing |
| Apply at a given sample index | Exact, but needs a sample counter and comparator; only Doppler pre-correction would use it, and Costas tracks Doppler (0.84 Hz rms, `sync_doppler_track.csv`) |

## Decision

- **Format** (`docs/protocol.md` "Control commands"): a datagram on the replay port whose byte 0 has bit 7 set is a
  command. SET_NCO is exactly 8 bytes: u32 `0x8000_0001`, then the u32 NCO word, both big-endian. Anything else
  with bit 7 set (wrong length, truncated, unknown code) is refused and counted.
- **`rtl/io/ctrl_rx.sv`** snoops the `udp_rx` → ingest stream (beat = tvalid && tready) and never stalls it.
  `iq_udp_ingest` consumes command datagrams without writing, moving its window or counting. Read as a seq, bytes
  0–7 of a command are ≥ 2⁶³, far beyond the window: without the check the ingest would skip every pending
  datagram as lost.
- **Timing:** a SET_NCO is accepted only while the DDC has taken no sample since the MAC left reset. The check
  includes the same clock's sample, and `set_o` is combinational on the command's last beat, so a word accepted on
  a clock with no sample taken is in place for the next sample.
- **Reset:** the word resets to the `FREQ_WORD` parameter (150 kHz) only on the core reset. A MAC restart (request
  0005 stopgap) keeps it, like `mac_restarts`; `ctrl_ok`/`ctrl_bad` restart with the MAC like fields 0–16.
- **Confirmation:** stats fields 26–28 (`nco_word`, `ctrl_ok`, `ctrl_bad`; appended, so the version stays 2). The
  command is a valid datagram on the replay port, so it also teaches the board the host's address, and stats start
  at once. The host (`scripts/board_rx.py set_nco`) sends the command, waits for a stats packet echoing the word,
  retries up to 5 times, and only then starts the replay. The confirmation also orders the command before the
  replay.

## Consequences

- One bitstream serves every recording: `make board BOARD_TOP=arty_rx_eth_top` without `BOARD_GENERICS`; `rx-check`
  and `ber_board.py` set the word per replay.
- `arty_ddc_eth_top` uses the same ingest, so it ignores commands too, but it has no `ctrl_rx`: commands sent to it
  show only as `udp_ok` minus the ingest's counts. It keeps its build-time word.
- More commands (loop gains, thresholds: buildplan §3.1) get new codes with bit 31 set. Loop gains are build
  parameters from `rx_config_pkg` until a measurement shows a recording needs others.
- `gs-replay` (C++) does not send commands yet; the Python host tools do. Phase F's ground station takes it over.

## Measured evidence

- `test_ctrl_rx.py` against a model written from `docs/protocol.md`: every datagram shape (replay, good SET_NCO,
  truncated, one byte short and long, unknown code, 1 byte, the pattern without bit 7, the pattern at byte 8, a
  1-byte command after a replay datagram ending in the pattern) back to back and with idle clocks; SET_NCO with
  lock toggling. Six planted bugs (lock ignored, length check loosened, truncation ignored, command bit taken from
  bit 6, word bytes rotated, refused commands not counted) each fail. Removing the length check outright only
  tripped Verilator's unused-signal warning, so the case of a short command after a replay datagram ending in the
  pattern was added; the loosened check then failed.
- `test_iq_udp_ingest.py` `commands_ignored` at 4, 2 and 1 slots: commands between swapped datagrams change no
  sample and no counter. Three planted bugs (window moved by a command, commands counted as bad, command bytes
  written into a slot) each fail.
- `test_arty_rx_eth_top_full.py` (sim-full): the board top built with the 150 kHz default decodes the 151 kHz
  stimulus bit-exact after SET_NCO; a second SET_NCO mid-replay is refused (`ctrl_bad` 1); the word survives a MAC
  restart (both pass, 2026-11-09). Three planted bugs each fail: the DDC fed the build parameter instead of the
  commanded word (0 CADUs of 3), the lock never applied in the top (the late word is taken: 0 of 3), the word reset
  by a MAC restart (0 CADUs of 2 after it).
- Board build (`board_arty_rx_eth_top.csv`): WNS +0.256 ns, `ctrl_rx` 19 LUTs, 117 FFs; the new worst path is the
  ingest's `seq` window compare into `ctrl_rx`'s counter enables.
- Hardware: `[TBD]`.
