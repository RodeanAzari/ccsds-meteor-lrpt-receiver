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
- [ ] Screenshot (you, Vivado GUI): the ILA waveform window on the same capture. Run `make board ILA=1`, claim the
      board, open Hardware Manager, program `build/board/arty_ddc_rom_top_ila.bit` with
      `arty_ddc_rom_top_ila.ltx`. Set trigger `bb_tvalid == 1` and `led_o_OBUF_1 == 0` (capture full = 0), capture
      condition the same (AND), depth 16384, trigger position 0. Arm, then reset the board (RESET button, or open
      the serial port). Show `bb_tdata` split as two signed 16-bit rails (Q = [31:16], I = [15:0]) in analog view,
      zoomed to roughly the first 128 samples. Crop to the waveform.
- [ ] Photo: the Arty running the bring-up design, LD4–LD6 lit (heartbeat, snippet played, capture full), USB cable
      to the host visible
- [ ] Screen recording or screenshot: terminal running `make prog board-check` ending in
      "16384 outputs, 0 mismatches"
