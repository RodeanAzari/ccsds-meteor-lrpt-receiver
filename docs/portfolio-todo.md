# Portfolio captures outstanding

## Phase 0 (needs the capture kit)

- [ ] Photo: V-dipole antenna setup, showing orientation and clear sky
- [ ] Screenshot: SatDump waterfall during your own pass
- [ ] Image: SatDump's decoded image from that pass

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
- [ ] Deferred by the user on 2026-11-05 (not needed for now): Photo: the Arty running the bring-up design, LD4–LD6 lit (heartbeat, snippet played, capture full), USB cable
      to the host visible
- [ ] Screenshot (you): terminal running `make eth-check BOARD_TOP=arty_ddc_eth_top IFACE=169.254.235.36 SPEED=1,5`
      showing "link up", the gs-replay lines and "16384 outputs, 0 mismatches" for both
      (`docs/media/2026-11-07_phase-b_eth-check-terminal.png`). Claim the board first.
- [ ] Photo (you): the Arty with the Ethernet cable and USB cable in, LD4 (heartbeat) and LD5 (capture full) lit
      after a replay (`docs/media/2026-11-07_phase-b_arty-ethernet.jpg`)

