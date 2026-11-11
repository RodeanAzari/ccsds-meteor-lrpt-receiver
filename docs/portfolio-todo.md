# Portfolio captures outstanding

## Phase 0 (needs the capture kit)

- [ ] Photo: V-dipole antenna setup, showing orientation and clear sky
- [ ] Screenshot: SatDump waterfall during your own pass
- [ ] Image: SatDump's decoded image from that pass

## Phase F (ground station)

- [ ] Terminal recording (you; `sudo apt install asciinema`, not on this host yet): `gs-view` live during a board
      replay at 1×. Claim the board, `rm -rf build/board_gs_rx`, then in two terminals:
      1. `asciinema rec docs/media/YYYY-MM-DD_phase-f_gs-view.cast -c "build/gs-Release/gs-view build/board_gs_rx/0_1x"`
         (it waits for the status file)
      2. the committed command from `data/results/board_gs_rx.md` (`PYTHONPATH=. .venv/bin/python
         scripts/board_gs_rx.py ... --speed 1,5,5.6`): its first replay is the 1× one gs-view watches; it rewrites
         `board_gs_rx.csv` with a fresh run of the same command (commit it or `git checkout` it)
      Expect sync LOCKED, CADUs climbing to 298, FER 0.000 %, then [final] 10 s after the last CADU, and gs-view
      exits. The .cast is text; a GIF made from it (agg) must stay ≤ 8 MB.

## Phase E (whole receiver on the board)

First decode on hardware, 2026-11-08: the synthetic recording replayed through `arty_rx_eth_top`, CADUs back over
Ethernet (`board_rx_eth.csv`). Claim the board first.

- [ ] Screenshot (you): terminal running `make rx-check IFACE=169.254.235.36 SPEED=1` showing "link up", the
      gs-replay line and the "CADU packets ... match the truth" summary
- [ ] Photo (you): the Arty during a replay, LD5 (frame sync locked) lit and LD6 toggling per CADU (LD7 latches on any
      ingest gap, so it lights when the host reorders datagrams; `rx-check` prints `ingest_gap`)
- [ ] Screenshot: Vivado device view of `arty_rx_eth_top` (buildplan §9 Phase E media), from
      `build/board/arty_rx_eth_top` after `make board BOARD_TOP=arty_rx_eth_top`
- [ ] Real-decode stats from a real pass (Phase 0 recording first)

## Phase C (synchronization)

No physical captures in this phase. The generated media below come from synthetic signals; regenerate them from the
real recording once there is one.

- [x] GIF: constellation locking, ring → four clusters (`docs/media/2026-11-05_phase-c_constellation-lock.gif`,
      `make plots`; bit-true chain, synthetic, 15 dB)
- [x] Plot: lock time vs. carrier error (`docs/media/2026-11-05_phase-c_lock-time.png`, `make plots`)
- [x] Plot: Doppler tracking at 30 Hz/s (`docs/media/2026-11-05_phase-c_doppler-tracking.png`, `make plots`)
- [ ] The same GIF from the real recording

## Phase B (DDC on the board)

- [x] Plot: spectrum before/after the DDC, from board data (`docs/media/2026-11-04_phase-b_ddc-spectrum-board.png`,
      `make plots`)
- [x] Plot: ILA capture of baseband I/Q vs. the model (`docs/media/2026-11-04_phase-b_ddc-ila-baseband.png`,
      `make plots`)
- [x] Screenshot: Vivado ILA waveform of the DDC output, I/Q as signed analog traces, samples 0–140
      (`docs/media/2026-11-04_phase-b_ila-waveform.png`). Checked: sample 15 reads I = −81, Q = −185, as in the
      model. From `build/board/ila_ddc.ila` (`make ila-capture`); trigger settings in
      `docs/reports/board/arty_ddc_rom_top_ila/ila_capture_settings.txt`.
- [x] Screenshot: terminal running `make prog board-check` ending in "16384 outputs, 0 mismatches"
      (`docs/media/2026-11-05_phase-b_board-check-terminal.png`)
- [x] ~~Photo: the Arty running the ROM bring-up design~~: replaced by the 2026-11-07 Ethernet photo (user's call)
- [x] Screenshot (you): terminal running `make eth-check BOARD_TOP=arty_ddc_eth_top IFACE=169.254.235.36 SPEED=1,5`
      showing "link up", the gs-replay lines and "16384 outputs, 0 mismatches" for both
      (`docs/media/2026-11-07_phase-b_eth-check-terminal.png`). Claim the board first.
- [x] Photo (you): the Arty with the Ethernet cable and USB cable in, LD4 (heartbeat) and LD5 (capture full) lit
      after a replay (`docs/media/2026-11-07_phase-b_arty-ethernet.webp`; LD7 error off)

