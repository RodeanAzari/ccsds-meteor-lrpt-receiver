# Portfolio captures outstanding

## Buildplan §9 review, 2026-11-23 (phases 0, A, C, D, E)

Met, with evidence in the README: Phase 0 spec, own pass decoded by SatDump, antenna photo, waterfall, image; Phase A
model = SatDump on the own pass, BER vs. theory, bit-true + fixed-point.md, constellation; Phase C RTL, lock
time/range, Doppler tracking, **lock on the real recording (on the board)**, GIF and plots (synthetic); Phase D
incremental Viterbi, ASM correlator + FSM, hardware BER vs. model, 3-/4-bit and traceback sweeps, BER plot; Phase E
RS/ASM/PN/chain, RS(544,514) instance (fpga-rs-core, KP4), **real pass on the FPGA = SatDump bit for bit**,
Viterbi and Viterbi+RS hardware BER, timing closed + per-block utilization, hero image.

Needs you (physical captures, listed in the phase sections below): Phase 0 whole-setup photo; Phase E Vivado device
view, rx-check terminal, Arty LED photo; Phase F gs-view asciinema, demo video.

Claude can generate: Phase C constellation GIF from the real recording (done 2026-11-23); Phase D waveform of
ACS/traceback (done 2026-11-23: sampled in cocotb, `docs/media/2026-11-23_phase-d_viterbi-waveform.png`); Phase E
real-decode stats (done 2026-11-23: the real-pass run's terminal output in the README).

Not met as written, decided by the user 2026-11-23:
- Phase 0/A "a public M2-x 72k recording decoded": **waived**; none is downloadable (docs/log.md 2026-11-14), the own
  2026-11-21 pass stands in.
- Phase D "ILA capture of path metrics": **done 2026-11-23**: 1,023 steps equal to the model
  (`viterbi_board_ila.csv`), heatmap `docs/media/2026-11-23_phase-d_viterbi-ila-path-metrics.png`. Optional (you):
  screenshot of the capture in Vivado's waveform view, `build/board/ila_acs.ila` (display_hw_ila_data).
- Phase E "hardware BER, uncoded": **waived**; no tap before the Viterbi decoder (README Limitations), model curve only.

## Phase 0 (needs the capture kit)

- [x] Photo: V-dipole antenna setup, showing orientation and clear sky (2026-11-21 pass, the first decoded,
      `docs/media/2026-11-21_phase-0_antenna-setup.webp`, in the README under Architecture; 2026-11-14 photo kept)
- [ ] Photo (you): the whole setup in one frame: V-dipole, SAWbird+ and RTL-SDR, laptop, and the Arty on its
      Ethernet cable
- [x] Screenshot: SatDump waterfall during your own pass (2026-11-21 recording replayed in satdump-ui at ~47%: Viterbi and deframer SYNCED, SNR 11.4 dB; stale status bar cropped off. `docs/media/2026-11-21_phase-0_satdump-waterfall.png`)
- [x] Image: SatDump's decoded image from that pass (2026-11-21, 4,583 CADUs): MSA natural colour with map, rotated north-up, `docs/media/2026-11-21_phase-0_satdump-image.webp`; lock GIF (first 15 s of a screen recording of the replay, original off-repo) `docs/media/2026-11-21_phase-0_satdump-lock.gif`; both in the README under Architecture

## Phase A (golden model on a real pass)

- [x] Plot: frames per 30 s, float model vs. SatDump, with the carrier offset, 2026-11-21 pass
      (`docs/media/2026-11-21_phase-a_real-pass-model.png`, `make plots`; in the README under Architecture)
- [x] Image (Phase E, 2026-11-22): MSU-MR image from the CADUs this receiver's RTL decoded on the board, next to
      SatDump's (`docs/media/2026-11-21_phase-e_msu-mr-board-vs-satdump.jpg`, `scripts/msu_mr_compare.py`)

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

- [ ] **Demo video (you, 60–120 s; buildplan §11 demo video), the whole setup in action.** Requested 2026-11-13.
      In frame together: the V-dipole, SAWbird+ and RTL-SDR V3, and the Arty with its Ethernet cable, all attached
      to the laptop. On screen: the antenna picking up the pass (SatDump waterfall, or a live terminal or
      dashboard view), the board and Ethernet processing it (`gs-view`: sync, CADU count, FER, the board's
      counters), and the end result (the decoded image). Unlisted YouTube or a GitHub attachment, linked from the
      README; never committed.
      Open question, decide before filming: the receiver is built to replay recordings, so the planned cut is the
      pass captured live, then that recording replayed into the board. A truly live chain (`rtl_sdr` streamed
      through `gs-replay` during the pass) would need streaming input in gs-replay, and the coarse NCO estimate
      before the first sample (ADR 0002, 0014). It isn't the "RF ADC into the FPGA" that §10 rules out, but it
      isn't built either. Needs the real decode (Phases C–F on a recording) first.

## Phase E (whole receiver on the board)

First decode on hardware, 2026-11-08: the synthetic recording replayed through `arty_rx_eth_top`, CADUs back over
Ethernet (`board_rx_eth.csv`). Claim the board first.

- [ ] Screenshot (you): terminal running `make rx-check IFACE=169.254.235.36 SPEED=1` showing "link up", the
      gs-replay line and the "CADU packets ... match the truth" summary
- [ ] Photo (you): the Arty during a replay, LD5 (frame sync locked) lit and LD6 toggling per CADU (LD7 latches on any
      ingest gap, so it lights when the host reorders datagrams; `rx-check` prints `ingest_gap`)
- [ ] Screenshot: Vivado device view of `arty_rx_eth_top` (buildplan §9 Phase E media), from
      `build/board/arty_rx_eth_top` after `make board BOARD_TOP=arty_rx_eth_top`
- [x] Real-decode stats from a real pass: `board_gs_rx.py` output and gs-rx's final counters (board stats
      included) from the 2026-11-22 1× replay, in the README under "On the board"; raw files in
      `docs/reports/board/real_pass_2026-11-21/`

## Phase C (synchronization)

No physical captures in this phase. The generated media below come from synthetic signals; regenerate them from the
real recording once there is one.

- [x] GIF: constellation locking, ring → four clusters (`docs/media/2026-11-05_phase-c_constellation-lock.gif`,
      `make plots`; bit-true chain, synthetic, 15 dB)
- [x] Plot: lock time vs. carrier error (`docs/media/2026-11-05_phase-c_lock-time.png`, `make plots`)
- [x] Plot: Doppler tracking at 30 Hz/s (`docs/media/2026-11-05_phase-c_doppler-tracking.png`, `make plots`)
- [x] The same GIF from the real recording (`docs/media/2026-11-23_phase-c_constellation-lock-real.gif`,
      `make plots`; bit-true chain on the committed 2.4 s snippet of the 2026-11-21 pass)

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

