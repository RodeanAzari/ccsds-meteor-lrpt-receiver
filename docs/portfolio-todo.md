# Portfolio captures outstanding

## Phase 0 (needs the capture kit)

- [ ] Photo: V-dipole antenna setup, showing orientation and clear sky
- [ ] Screenshot: SatDump waterfall during your own pass
- [ ] Image: SatDump's decoded image from that pass

## Phase B (DDC on the board)

- [x] Plot: spectrum before/after the DDC, from board data (`docs/media/2026-11-04_phase-b_ddc-spectrum-board.png`,
      `make plots`)
- [x] Plot: ILA capture of baseband I/Q vs. the model (`docs/media/2026-11-04_phase-b_ddc-ila-baseband.png`,
      `make plots`)
- [x] Screenshot: Vivado ILA waveform of the DDC output, I/Q as signed analog traces, samples 0–140
      (`docs/media/2026-11-04_phase-b_ila-waveform.png`). Checked: sample 15 reads I = −81, Q = −185, as in the
      model. From `build/board/ila_ddc.ila` (`make ila-capture`); trigger settings in
      `docs/reports/board/arty_ddc_rom_top_ila/ila_capture_settings.txt`.
- [ ] Photo: the Arty running the bring-up design, LD4–LD6 lit (heartbeat, snippet played, capture full), USB cable
      to the host visible
- [ ] Screen recording or screenshot: terminal running `make prog board-check` ending in
      "16384 outputs, 0 mismatches"
