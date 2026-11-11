# Lab notebook

## 2026-11-02: Phase 0, signal spec from SatDump source

**Done**

- Read SatDump 1.2.2's `meteor_m2-x_lrpt` pipeline and wrote `docs/signal-spec.md`.
- Added `scripts/verify_signal_spec.py`, which checks the derived constants against SatDump's. All checks pass.

**Found**

- Roll-off is 0.5, RS basis is conventional, and conv output is G1 then G2 with no inversion.
- The pipeline uses NRZ-M, which the original architecture left out. Without it, no ASM would ever match. See ADR 0001.
- SatDump's CADU output keeps channel errors in the RS parity bytes and ASM, so `gs-diff` has to compare the 892 data
  bytes rather than the whole frame.

**Not done**

- No recording decoded. A search found no public archive of 72k baseband recordings, and SatDump isn't installed yet.
- Nothing in the spec has been confirmed on a real signal. Which rail leads and which carries G1 are still open.
- Current satellite mode unknown: the newest mode reports found date from 2024.

## 2026-11-02 (continued): Phase A float model on synthetic signals

**Done**

- Wrote the transmit chain, a parameterized RS codec (also tested as RS(544,514) over GF(2^10)) and a float receiver.
- Checked the RS encoder against libcorrect, built from SatDump's own source.
- Uncoded waveform BER matches Q(sqrt(2Eb/N0)) from 0 to 8 dB. Soft Viterbi BER is 1.79e-5 at 4.0 dB, against a
  union bound of 1.81e-5. Source: `data/results/ber_awgn.csv`.
- The full chain recovers 190 of 200 frames from 2.5 dB up, with a 1 kHz offset, a 30 Hz/s ramp and a timing
  offset. The 10 missing are the first and last frame of each run. Source: `data/results/fer_full_chain.csv`.
- Carrier-before-timing decoded every reachable frame at every offset, and plain-Gardner-first decoded none.
  Recorded in ADR 0002.

**Bugs**

1. Symptom: Q leading with a 90° phase gave zero frames on a clean signal. Root cause: sync threshold 0.55 sat
   inside the random-data correlation range (about 0.6 to 0.7), so a chance pair of peaks locked a wrong hypothesis
   and the flywheel held it. Fix: threshold 0.75, plus a regression test.
2. Symptom: 223 frames synced out of 200 sent. Root cause: after a cycle slip, search restarted inside the flywheel
   window, and the new phase hypothesis found the emitted frames again. Fix: hold flywheel frames until the lock is
   confirmed, and restart past the last confirmed ASM. Regression test fails on the old code (15 frames reported
   for 12 sent).
3. Symptom: the "after lock" constellation plot showed a cross. Root cause: the plot started on an odd sample and
   paired strobes with midpoints. Plot-only; the decoder was correct. Fix: start on an even sample.

**Not done**

- Running SatDump was blocked by the permission check, so the synthetic-file cross-check is the user's step.
- No real recording yet.

## 2026-11-03: SatDump cross-check on the synthetic recording; kit change

**Done**

- Moved the project into WSL (`~/CCSDS`), deleted the Windows copy after checking it held nothing the WSL copy lacked,
  and pushed to a private GitHub repo.
- Installed SatDump 1.2.2+gb79af48-2 from Ubuntu 26.04's archive. The spec was read from commit `7aef0fe`, also 1.2.2.
- SatDump decoded `make synthetic-iq`'s recording: 258 of 300 CADUs, all 258 matching truth on the data bytes.
  Source: `data/results/satdump_crosscheck.csv`. That is the first check of our transmit chain by an independent
  decoder.
- The missing leading frames track the carrier offset (first frame 1 at 0 Hz, 70 at a static 1 kHz, 38 at 1 kHz plus
  30 Hz/s), so they are SatDump's acquisition time.
- Kit: RTL-SDR Blog V3 (V4 out of stock) plus Nooelec SAWbird+ NOAA on the V3's bias tee. CLAUDE.md §1 updated.

**Bugs**

1. Symptom: the cross-check script reported 0 of 258 frames matching, where a manual check gave 258. Root cause:
   `build_cadus` returns a (frames, 1024) array, and the script sliced it as a flat byte stream. Fix: index by row.

**Not done**

- Why SatDump drops the last 4 frames, and why it exits with code 1, is not established. Neither affects the CADUs.
- Still no real recording.

## 2026-11-03 (continued): bit-true DDC

**Done**

- `model/ddc_fixed.py`: streaming, causal integer model of ingest, DC block, NCO, mixer, CIC ÷4 and compensation
  FIR, at the widths in `docs/fixed-point.md`. ADRs 0003 (NCO) and 0004 (CIC).
- With the bit-true DDC, the receiver decodes the same frames as with the float DDC at every Eb/N0 from 2 to 8 dB,
  with soft-symbol SNR within 0.01 dB. DDC SQNR is 51.0–53.7 dB on noisy inputs, 64.1 dB clean.
  Source: `data/results/ddc_fixed_chain.csv`.
- NCO SFDR is 71.6–72.8 dB over 64 random tuning words (`data/results/ddc_nco_sfdr.csv`).
- Six tests, two checked by planted bugs: a quadrant slip in the NCO fails 3 tests; a DC block with no feedback
  fails 1. The CIC test also runs one register bit short and requires that to fail.

**Not done**

- Why DDC SQNR is lower with noise than without is not established. It doesn't reach the soft symbols.
- Bit-true model from the RRC on.

## 2026-11-03 (continued): bit-true RRC

**Done**

- `model/rrc_fixed.py`: causal 57-tap RRC (±8 symbols, α = 0.5), taps s1.17, exact accumulator (≤ 40 bits), s16
  output rounded and saturated. Formats in `docs/fixed-point.md`. `receiver.py` now exposes `rrc_taps()`,
  `normalize_rails()` and `demodulate_filtered()` so the bit-true path can join the float chain after the RRC.
- With bit-true DDC + RRC, the receiver decodes the same frames as with bit-true DDC + float RRC at every Eb/N0 from
  2 to 8 dB (18 of 20), soft SNR within 0.01 dB. RRC SQNR 63.3–67.6 dB, about 12 dB below the DDC's.
  Source: `data/results/rrc_fixed_chain.csv`.
- Four tests, checked by two planted bugs: an RRC gain of 4 fails the saturation-bound and SQNR tests; taps
  quantized to 10 bits fail the DC-gain and SQNR tests.

**Not done**

- The AGC (the float chain's `normalize_rails()`) and the loops are not bit-true yet.
- Still no real recording.

## 2026-11-04: bit-true sync loops

**Done**

- RF kit ordered (arrives about 2026-11-25). The tb/common rule now follows coord.py: P2's `tb/common/` by path until
  `tb-common-v0.1`, then the pinned tag (CLAUDE.md).
- `model/sync_fixed.py`: AGC (power detector, target rail rms 4096), Costas (shares the DDC NCO table, 48-bit
  frequency integrator), Farrow cubic in Horner form, per-rail Gardner, all integer. Per ADR 0002 the host's coarse
  estimate goes into the DDC NCO word.
- With the whole demodulator bit-true, the receiver decodes the same frames as float at every Eb/N0 from 2 to 8 dB at
  1 and 3.4 kHz offsets, 30 Hz/s ramp. Tracking error is 1.7–4.0 Hz rms. AGC settles in 60–104 ms.
  Source: `data/results/sync_fixed_chain.csv`, `data/results/sync_agc_settle.csv`.
- Four tests, checked by three planted bugs: AGC target ×2, Costas ki without fraction bits, a Farrow coefficient sign.

**Bugs**

1. Symptom: the Farrow test failed by 2,252 LSB. Root cause: the test drew samples up to full scale, and the cubic's
   overshoot saturated s16 as designed. Fix: draw within ±4× rail rms, the AGC's working range.
2. Symptom: the Farrow error reached 1.13 LSB against a 1-LSB assertion. Root cause: the assertion was wrong. Three
   internal roundings plus the output rounding bound the error at 1.25 LSB. Fix: assert the derived bound.
3. `docs/fixed-point.md` said the AGC settles near a gain of 4. Measured: 5.9–9.8. Fixed from the CSV.

**Not done**

- At 3.4 kHz, bit-true soft SNR is 0.04–0.18 dB better than float. Likely cause: the coarse correction comes before
  the RRC. Not established.
- Soft-symbol quantization, bit-true Viterbi. Still no real recording.

## 2026-11-04 (continued): soft-decision width and Viterbi ACS

**Done**

- `model/viterbi_fixed.py`: midrise power-of-two quantizer, distance branch metrics, modulo path metrics. On the same
  quantized input it matches the float decoder bit for bit; per symbol the float correlation is a constant minus
  this distance, so that is expected and now shown.
- Soft width (ADR 0005): best step ONE/4 for both widths. Eb/N0 at BER 1e-5: unquantized 4.15 dB, 4-bit 4.28 dB,
  3-bit 4.39 dB. Chose 4-bit. Source: `data/results/soft_width_ber.csv`, plot
  `docs/media/2026-11-04_phase-a_soft-width-ber.png`.
- Path metrics (ADR 0006): modulo, width from the spread bound (7·BMmax). Largest spread seen at σ = 1.0: 48 (3-bit,
  bound 84), 104 (4-bit, bound 180).
- Three tests, checked by two planted bugs: a plain compare on wrapped metrics, and a quantizer offset off by one.

**Bugs**

1. Symptom: the first step sweep picked the largest step tried for 4 bits. Root cause: the sweep range stopped at the
   optimum's edge. Fix: sweep shift 7–12 for both widths; the optimum is now inside.
2. Symptom: no 1e-5 crossing for the unquantized curve. Root cause: the 4.5 dB point stopped at the 30 M-bit cap with
   75 errors (an upper bound, excluded). Fix: 60 M-bit cap.

**Not done**

- Area per width is `[TBD]` until Phase D synthesis. Traceback depth and survivor scheme. `docs/design.md`.

## 2026-11-04 (continued): traceback depth and survivor memory

**Done**

- `model/viterbi_fixed.py`: ACS split from traceback; per-bit sliding traceback from the best state or state 0, as
  the planned BRAM traceback does it.
- Depth sweep (12–96, both starts, 12.0 M bits per Eb/N0, shared decisions): from the best state, depth 48 is 2–5%
  above full-block BER at 2.5–3 dB; from state 0, depth 96 equals full-block (+0.1% at 2.5 dB). Chose state 0,
  depth 96: no 64-way minimum tree, and clocks per bit are nearly free. Source: `data/results/traceback_depth.csv`.
- ADRs 0007 (BRAM survivors, per-bit traceback) and 0008 (depth 96 from state 0). `docs/design.md` written.
- Two tests, checked by two planted bugs: traceback one step off, and the best-state start ignored.

**Not done**

- Throughput (≈ 1 Mbit/s at 100 MHz, 14× real time) is derived, not measured. It would cap an RRC-injection BER
  campaign near 14× real time. Chunked traceback is the fallback.
- Depth 96 is outside CLAUDE.md §3.6's 35–50; ADR 0008 says why.

## 2026-11-04 (continued): Phase B DDC RTL

**Done**

- `tb-common-v0.1` was tagged by P2 (fpga-coord soft gate met). Pinned in `requirements.txt` as a pip install from
  git at the tag, with cocotb 2.1.0. `make lint` and `make sim` now work; `make ci` runs both.
- RTL in `rtl/ddc/`, each block bit-exact against `model/ddc_fixed.py` under random tvalid gaps and tready stalls:
  `ddc_ingest` (cu8 → s9 → DC block, s10), `ddc_nco_mixer` (5-stage, global stall), `ddc_cic` (÷4, order 3, 22-bit
  wrapping registers), `ddc_comp_fir` (31 taps, one time-shared multiplier per rail), `ddc_top`.
- ROM/coefficient files (`nco_lut.mem`, `comp_fir_taps.mem`) are generated from the model by
  `scripts/gen_rtl_tables.py`; `make model-test` fails if a committed file is stale.
- Whole chain on a modulated signal (151 kHz carrier, 30 Hz/s ramp, 6 dB, DC offset): 6,000 outputs, 0 mismatches.
  Throughput 9.0 cycles per input sample against 97.7 at 100 MHz: 10.8× real-time headroom
  (`data/results/ddc_rtl_sim.csv`). 13 cocotb tests passing.
- Planted bugs, each caught: DC accumulator 20 bits instead of 24; a sign error in one NCO quadrant; CIC registers one
  bit short (caught only by the full-scale tests: at the mixer's real level, ≤ 11,563, 21 bits suffice); the FIR
  dropping its last tap.

**Bugs**

1. Symptom: the full-scale DC-step test peaked at 496, not 510. Root cause: the test, not the RTL; 3,000-sample
   segments are 2.9 time constants, so the previous step had not settled (255·e^−2.93 ≈ 14). Fix: 16,000-sample
   segments. The RTL matched the model throughout.
2. Symptom: cocotb could not import `model`. Root cause: the cocotb runner overwrites PYTHONPATH with `sys.path`.
   Fix: put the repo root on `sys.path` in `tb/cocotb/run.py`.

**Not done**

- Board: a BRAM-ROM IQ snippet top with UART/ILA readout (`eth-core-v0.1` not tagged). `gs-replay`.
- Phase B media: spectrum before/after DDC, ILA capture of baseband I/Q.

## 2026-11-04 (continued): Vivado flow and DDC timing closure

**Done**

- `scripts/vivado.sh` runs Vivado 2025.2 in batch with this machine's workarounds (a user-local en_US.UTF-8 locale,
  ncurses compat libraries), without sourcing `settings64.sh` into the shell. `syn/synth_ooc.tcl` synthesizes,
  places and routes one block out of context; `make synth-ooc TOP=<top>` runs it and writes
  `data/results/synth_<top>.csv` from the reports in `docs/reports/ooc/<top>/`.
- `ddc_top` at 100 MHz on xc7a100t-1, post-route: WNS +0.661 ns, WHS +0.112 ns, 0 failing endpoints. 1,036 LUTs,
  1,659 FFs, 1 RAMB18 (NCO table), 6 DSP48E1 (4 mixer, 2 FIR): every multiplier inferred into a DSP
  (`data/results/synth_ddc_top.csv`).

**Bugs**

1. Symptom: Vivado aborted at start-up with `locale::facet::_S_create_c_locale name not valid`. Root cause:
   `rdiArgs.sh` forces `LC_ALL=en_US.UTF-8`, which this WSL install doesn't generate. Fix: `LOCPATH=~/.locale`
   (already built for another project) in `scripts/vivado.sh`. The wrapper's own first version also exited silently:
   an unmatched install glob made `ls` fail under `pipefail`.
2. Symptom: first OOC run missed 100 MHz by 3.262 ns on 64 endpoints. Root cause: `ddc_cic` did three integrator
   adds, three comb subtracts, rounding and saturation in one cycle. Fix: pipeline the combs one stage each; a
   decimation instant is accepted only when the comb pipe and output register are free. Outputs and throughput
   unchanged (all CIC and top tests bit-exact, still 9.0 cycles per sample).

**Not done**

- Worst path is now the DC-block accumulator (8.73 ns). Thin margin for the integrated build; pipelining its
  rounding is the first fix if needed.
- Board top with the BRAM-ROM snippet, `gs-replay`, Phase B media.

## 2026-11-04 (continued): DDC on the board

**Done**

- Bring-up design `rtl/top/arty_ddc_rom_top.sv` (ROM → DDC → capture → UART) with `reset_sync`, `cdc_sync_bit`,
  `iq_rom_source`, `capture_dump`, `uart_tx`; `constr/arty_a7_100t.xdc`; `syn/impl_board.tcl`;
  `make board prog board-check`. A cocotb test decodes the UART pin in simulation and checks every output and the
  BTN0 repeat dump against the model (14 cocotb tests now).
- Board build at 100 MHz: WNS +1.521 ns, WHS +0.040 ns (`data/results/board_arty_ddc_rom_top.csv`).
- **On hardware: 16,384 DDC outputs, 0 mismatches against the bit-true model** (`data/results/ddc_board.csv`),
  on three CRC-checked runs with byte-identical dumps. Spectrum before/after from board data:
  `docs/media/2026-11-04_phase-b_ddc-spectrum-board.png`.
- Planted bug, caught by the board-top test: the capture buffer's stale-read bug (bug 3 below) put back.

**Bugs**

1. Symptom: board build missed 100 MHz by 0.155 ns on 7 endpoints. Root cause: the ROM's BRAM output fed the DC
   block's accumulator update, rounding and saturation in one cycle (9.51 ns, 12 logic levels), the path flagged
   after the OOC run. Fix: `ddc_ingest` split into three stages (convert, accumulate, round/saturate). Bit-exact
   tests unchanged.
2. Symptom: second board run reported 16,169 of 16,384 outputs wrong, from word 215 on. Root cause: not the DDC.
   Opening the serial port resets the board (a dump began 0.05 s after the port opened, with no programming or
   button), and programming then cut that dump off after 891 bytes; the host took the cut-off dump's header and read
   on into the next dump. The first run passed only because no DDC design was loaded yet. Fix: CRC-32 trailer on the
   dump; the host skips dumps that fail it (`scripts/tests/test_ddc_board.py` replays this case). Next run: the
   cut-off dump was skipped on its CRC and the real one matched.
3. Symptom (caught in review before simulation): `capture_dump` would have sent each word's predecessor. Root cause:
   the FSM loaded the BRAM read register in the cycle after changing the address, one cycle too early. Fix: a wait
   state.
4. Symptom: the "before" spectrum showed a notch, not a spike, at the DC offset. Root cause: Welch's default
   per-segment mean removal. Fix: `detrend=False`.
5. Process slip: a shell chain continued after a ruff failure and ran `make prog` without the fpga-coord board
   claim (the board was free; claimed properly on every run since). Board runs now use `set -e` and remove stale logs.
6. Also fixed: the top's default NCO word was written as 0x0258_0000 instead of 0x2580_0000 (150 kHz); caught by
   reading it back before the first simulation.

**Not done**

- ILA build and baseband I/Q capture; `gs-replay`; board photo.
- Why opening the port resets the design is not established; the CRC makes the check immune to it either way.

## 2026-11-04 (continued): gs-replay and the IQ transport format

**Done**

- `docs/protocol.md` started: IQ replay datagram = 8-byte big-endian sequence + 512 raw cu8 samples (1,032 B).
  It matches fpga-eth-core `examples/rx_stats`'s payload contract, so that harness can soak-test replay once
  eth-core-v0.1 exists. ADR 0009 covers the alternatives.
- `gs/`: CMake project (C++20, `-Wall -Wextra -Werror -Wconversion -Wshadow`, ASan/UBSan in Debug), `gs_core` library
  (packet build, deadline math, argument parsing), `gs-replay` binary. Pacing is real time, N× (3 decimals), or flat
  out, with absolute deadlines from the packet index. Every run logs the achieved rate, and a partial final datagram
  is reported, not sent. GoogleTest v1.15.2 is fetched at a pinned SHA-256.
- Tests: 8 GoogleTest cases (Release and Debug), plus 4 loopback pytest cases that run the sanitized binary and check
  sequence, byte-exact payload, tail reporting and pacing span. `make gs`, `make gs-test`; `make ci` now includes
  `gs-test` and passes.
- Planted bugs, both caught: sequence written little-endian (1 GoogleTest + 3 loopback failures); pacing sleep removed
  (2 loopback failures).

**Measured** (`data/results/gs_replay_loopback.csv`, loopback, synthetic recording)

- 1×: 68,266/68,266 datagrams, 0 sequence errors, byte-identical, 1.00× achieved over 34.133 s.
- 5×: same, 5.00× achieved; 7% of datagrams sent more than one 100 µs period late (WSL jitter), average exact.
- Flat-out: 124× on loopback; the Python measuring receiver dropped about 11% at about 250 k datagrams/s.
  A receiver limit; it doesn't apply to the 100 Mb/s link (≤ 5.69× by arithmetic).

**Not done**

- clang-format, clang-tidy, cppcheck and libFuzzer are not installed (no sudo). §5.3 static analysis is not running.
  There is no parser yet to fuzz; the IQ parser lives on the board.
- Replay to the Arty: gated on eth-core-v0.1 (P2). WSL2 multicast egress to the board NIC is untested.

## 2026-11-04 (continued): ILA capture of the DDC output

**Done**

- `make board ILA=1`: `syn/impl_board.tcl` inserts an ILA after synthesis. The RTL is unchanged and the functional
  build doesn't depend on it. Probes are `bb_tdata` (32), `bb_tvalid`, the capture buffer's `full` (its tready is
  exactly `!full`) and `rom_done`. Storage qualification keeps only handshake cycles, so 16,384 entries hold every
  output of the snippet. Timing: WNS +1.750 ns, WHS +0.024 ns; the ILA costs 1,449 LUTs, 2,461 FFs and 16 RAMB36
  (`data/results/board_arty_ddc_rom_top_ila.csv`).
- `make ila-capture` (`syn/ila_capture.tcl`): programs over JTAG (Vivado hw_server works through usbipd in WSL),
  arms on the first handshake, then resets the design by opening the serial port (observed behaviour; the mechanism is not established).
  Writes the CSV, then `scripts/ddc_board.py ila-check` compares it with the model.
- Plot `docs/media/2026-11-04_phase-b_ddc-ila-baseband.png` (`make plots`).

**Measured**

- ILA: 16,384 outputs, 0 mismatches vs. `model/ddc_fixed.py` (`data/results/ddc_board_ila.csv`). This is a second
  readout path, independent of the UART dump, and it also proves trigger alignment and probe bit order. The parser
  refuses captures that don't start at the trigger or that hold non-handshake rows. 3 new tests, and a planted I/Q
  swap is caught.

**Bugs**

1. Symptom: `build/board/iq_rom.mem` vanished after each Vivado run. Root cause: Vivado copies `.mem` files into
   the run directory for synthesis and deletes the copies at exit. The ROM was generated *in* the run directory,
   so the "copy" was the original. It was harmless while `make board` regenerated it every time, but it broke a
   second Vivado run in the same directory. Fix: the ROM now lives in `build/board/rom/`.
2. Symptom: ILA insertion failed with "net bb_tready not found". Root cause: synthesis merges `bb_tready` into
   `capture_dump`'s full logic and renames hierarchy ports. Fix: probe `full` (via its LED net) and qualify on
   `bb_tvalid && !full`; every probe net is checked and the build fails loudly on a rename.
3. Symptom: the capture script's Python call died with "No module named 'encodings'". Root cause: Vivado's
   environment sets PYTHONHOME. Fix: `env -u PYTHONHOME -u PYTHONPATH` for that call.
4. Process: the gs-replay results sidecar was hand-written instead of generated by `analysis.common.write_result`.
   Moved the interpretation to `analysis/interpretations/`. Its run-to-run jitter numbers are now stated as ranges,
   because re-running changed them (late datagrams 69–304 at 1×; flat-out loss at the Python receiver 0.4–17%).

- 2026-11-05: re-captured with `make ila-capture` (0 mismatches again). The script now also writes the `.ila` file
  and the trigger/capture settings it used. The GUI screenshot was taken offline from that file.
- GUI lessons, for next time: pressing PROG clears the bitstream (re-program; the ILA is gone until then). A GUI
  trigger row left on rom_done == 1 stops the trigger from ever firing on the first output. Virtual buses built from
  expanded bits came out bit-reversed the first time; check one known sample against the model. hw_server crashed
  once over usbipd; killing it and reconnecting fixed it.

## 2026-11-05: README and Phase B media

**Done**

- `README.md` written to the CLAUDE.md §11.4 standard: claim title, at-a-glance table, status, Mermaid architecture,
  verification by layer, bugs table (15) and planted bugs (15), deep sections for every block (RTL where it exists,
  model decisions and `[TBD]` otherwise), on the board, demos, Vivado, results, limitations, build, layout,
  roadmap. Every number links to its CSV or report; every file link checked.
- Phase B media: ILA waveform screenshot (from the `.ila` file, offline) and the `make prog board-check` terminal
  screenshot. Board photo deferred by the user.
- Corrected my own unverified claim that the serial port resets the board through DTR. The behaviour is observed;
  the mechanism is not established (`docs/design.md`).
- CLAUDE.md status table: Phase B is now IN PROGRESS (it said NOT STARTED).

## 2026-11-05 (continued): C++ static analysis

**Done**

- `gs/.clang-format` (Google, 4-space, 110 columns), `gs/.clang-tidy` (bugprone, cert, clang-analyzer, concurrency,
  cppcoreguidelines, misc, modernize, performance, portability, readability; warnings are errors; 11 checks off, each
  with its reason in the file), `gs/tests/.clang-tidy` (two more off for GoogleTest), cppcheck. `make gs-lint`, in
  `make ci`. A planted unbraced `if` and a planted format error each fail it.
- First run: 58 clang-tidy errors in 14 checks. Fixed in code: missing braces, ignored printf/fclose results
  (cert-err33-c), precedence parentheses, `std::strerror` (not thread-safe) replaced by `std::system_category()`,
  implicit integer-to-bool, a signed/unsigned compare (`std::cmp_not_equal`), include guard for `#pragma once`, a
  missing const. The stdio file handle became POSIX `open`/`read` with an RAII `Fd` and a `read_full` loop that retries
  short reads and EINTR; that cleared the analyzer's stream-state findings and the ownership warning. Two NOLINTs,
  each with its reason: `deadline_ns`'s rate and speed are only used as a product, so swapping them is harmless;
  `from_chars` takes a range, not a C string. cppcheck: one finding (a variable's scope), fixed.
- `make ci` passes; the loopback tests re-ran against the new read path.

**Found**

- The README claimed "CI runs `make ci`", but there is no `.github/workflows/`. Corrected; hosted CI is a next step.
- `data/results/gs_replay_loopback.csv` was measured with the stdio read path. The new read path passes the same
  loopback tests (order, byte-exactness, tail, pacing), so the CSV wasn't re-run.

## 2026-11-05 (continued): hosted CI

**Done**

- `.github/workflows/ci.yml`: `make setup` + `make ci` in an `ubuntu:26.04` container on GitHub's ubuntu-24.04
  runner, so CI uses the development machine's tool versions. Verilator v5.050 is built from source and cached.
- First run (41977969472) green in 17 min, including the uncached Verilator build. Checked in the job log rather than
  trusting the badge: Verilator 5.050, Python 3.14.4, CMake 4.2.3, LLVM 21.1.8, cppcheck 2.19.0; 63 pytest,
  14 cocotb (0 skipped), 8 GoogleTest in each of the Release and sanitized builds, 4 loopback, and all three gs-lint
  tools ran. The only "skipped" lines are CMake's compiler self-checks.
- README: CI badge; the "no hosted CI" limitation removed.

**Not done**

- GitHub annotation: `actions/checkout@v4` and `actions/cache@v4` target Node.js 20, which is deprecated; they run on
  Node.js 24 for now. Bump them when newer majors are confirmed.

## 2026-11-05 (continued): Phase C, RRC matched filter RTL

**Done**

- `rtl/sync/sync_rrc.sv`: the RRC has the same arithmetic as the DDC's comp FIR (s18 taps, exact 40-bit
  accumulator, `>> 17` rounded and saturated to s16), so it instantiates `ddc_comp_fir` with 57 taps instead of
  adding a second FIR. Taps go to `rtl/sync/rrc_taps.mem` from `rrc_fixed.taps()` via `scripts/gen_rtl_tables.py`,
  covered by the staleness check in `make model-test`.
- `tb/cocotb/test_sync_rrc.py`, 4 tests: bit-true DDC output of 6 dB OQPSK (151 kHz, 30 Hz/s ramp) under random
  backpressure, 4,000 / 4,000 bit-exact; impulse centred and symmetric; sign-matched full-scale input clips, not
  wraps; throughput. `make sync-rtl-results` → `data/results/rrc_rtl_sim.csv`.
- Measured: 62 clocks per sample, 6.3× real time at 100 MHz. OOC at 100 MHz: WNS +2.453 ns, WHS +0.107 ns,
  616 LUT, 1,874 FF, 2 DSP48E1 (`data/results/synth_sync_rrc.csv`). Worst path: accumulator → round/saturate →
  output register.
- Planted bug: one tap in `rrc_taps.mem` changed; all four tests failed. Restored.
- `make ci` passes: 63 pytest, 18 cocotb, 8 + 8 GoogleTest, 4 loopback, lint clean.

**Found**

- The header comment first claimed NTAPS + 3 = 60 clocks per sample; the measurement says 62 (two cycles of
  output handshake). Corrected to the measured value.
- My first interpretation note said 16,000 samples were checked; it was 16,000 cu8 inputs, 4,000 RRC samples after
  the ÷4. Corrected before the result was committed.

**Not done**

- 6.3× real time caps the RRC-input injection mux for BER campaigns. That is about 220 s per 10⁻⁶ point, so it is
  fine for now; folding the symmetric taps through the DSP pre-adder would halve it if needed.

## 2026-11-05 (continued): Phase C, AGC RTL

**Done**

- `rtl/sync/sync_agc.sv`: the model's AGC updates the gain from each output before the next sample, so the RTL holds
  one sample in flight: take | x·g | round, saturate, output | yi² + yq² | error term | gain update. 6 clocks per
  sample (65× real time at 100 MHz). Ready only when idle with the output empty, as in the FIR.
- `tb/cocotb/test_sync_agc.py`, 3 tests, every output against `sync_fixed.agc()`: 12,000 samples of bit-true RRC
  output from gain 1.0 under random backpressure; 1,500 silent samples then a 1,000-sample full-scale burst (the
  unsaturated product exceeds s16, so clipping is exercised); throughput. 16,500 outputs bit-exact
  (`data/results/agc_rtl_sim.csv`).
- OOC at 100 MHz: WNS +2.344 ns, WHS +0.227 ns, 163 LUT, 68 FF, 4 DSP48E1 (`data/results/synth_sync_agc.csv`).
- Planted bugs, each failing all three tests: next sample accepted one stage early (gain update applied a sample
  late); rounding dropped from the gain step.
- `make ci` passes: 63 pytest, 21 cocotb.

**Found**

- Symptom: the saturation test, written to expect the gain to settle at 512 (rms exactly ONE for a ±32768 input),
  read 572. Root cause: not the RTL (it matched the model on every sample) but the model's update rule. The step
  `round((2·ONE² − p) >> 24)` is zero for power within ±25% of target, a dead zone of 0.87–1.12·ONE rms; a
  constant-envelope input stops wherever it enters it. Fix: the test asserts the dead-zone bound; the property is
  written up in `docs/fixed-point.md`. On noisy signals the bit-true chain already decodes the same frames as float,
  so the model is unchanged.
- My first version of that test also asserted the gain reaches its lower clamp of 1. It can't from s16 input: a
  saturated output moves the gain by at most −128 per sample and the loop settles at ~512. The upper clamp needs
  ~2¹⁹ silent samples. Neither clamp is exercised in RTL simulation.

## 2026-11-05 (continued): Phase C, Costas loop RTL

**Done**

- `rtl/sync/sync_costas.sv`: per-sample loop, one sample in flight: table read | mirror | rotate | round, saturate,
  output | detector terms | error, clamped | ki·e, kp·e | frequency | phase. 10 clocks per sample (39× real time).
  Gains are input ports (host control registers, CLAUDE.md §3.1). Its own copy of the DDC's quarter-wave table.
- `tb/cocotb/test_sync_costas.py`, 3 tests: 16,000 samples of bit-true AGC output with a 50 Hz residual (what is left
  after the host's coarse estimate, ADR 0002) and a 30 Hz/s ramp under random backpressure, where the loop pulls in
  and ends at 52.0 Hz; 8,000 samples with the frequency clamp at 20 Hz; throughput. 26,000 outputs bit-exact
  (`data/results/costas_rtl_sim.csv`).
- OOC at 100 MHz: WNS +2.360 ns, 469 LUT, 153 FF, 7 DSP48E1, 1 RAMB18 (`data/results/synth_sync_costas.csv`).
- Planted bugs: phase updated with the previous frequency, sgn(0) = +1 in the detector (each fails all three tests),
  upper frequency clamp removed (fails the clamp test). The first two were re-run after the detector split.
- `make ci` passes: 63 pytest, 24 cocotb.

**Found**

- The output register was loaded one stage before the rotator products were ready (`st_q[3]` instead of `[4]`).
  Caught by tracing the stage timing by hand before the first simulation.
- First synthesis met timing by only 0.512 ns: the phase detector (two conditional negations, subtract, clamp) in
  one cycle. Split over two stages: +2.360 ns, one more clock per sample, outputs unchanged.
- Choosing the test input showed how slow pull-in is at costas_bw 0.001: from a 1 kHz residual the loop does not
  lock within 20,000 samples; 50 Hz locks after ~5,000 samples (20 ms), 100–400 Hz do not within 16,000. This is
  the ADR 0002 reason for the coarse estimate, now with numbers from the bit-true model. A proper lock-range and
  lock-time sweep is a Phase C deliverable still to do.

## 2026-11-05 (continued): Phase C, Farrow + Gardner timing RTL

**Done**

- `rtl/sync/sync_timing.sv`: Farrow cubic resampler to 2 sps with the per-rail OQPSK Gardner detector. Each output's
  error sets the next position, so outputs go one at a time: fill a 4-sample window (1–2 new samples per output) |
  cubic coefficients | three Horner steps per rail | output | detector terms | product | error | ki·e, kp·e |
  integrator | position. Gains are input ports. 8.86 clocks per input sample (44× real time).
- `tb/cocotb/test_sync_timing.py`, 3 tests on bit-true Costas output of 6 dB OQPSK, 14,619 outputs bit-exact
  (`data/results/timing_rtl_sim.csv`):
  - half-symbol offset under random backpressure; the strobe eye ratio (mean/std of |soft|) ends at 2.08, against
    1.48 for the same input with the loop off. The test asserts that the baseline stays under the 1.9 threshold.
  - 100 ppm clock error with the integrator limit at one ki step, so the clamp acts on nearly every update.
  - throughput.
- The model stops one sample before the stream ends, so the test runs the model on the input plus one sample.
  That gives exactly the outputs the RTL emits.
- OOC at 100 MHz: WNS +0.745 ns, 938 LUT, 504 FF, 7 DSP48E1, no BRAM (`data/results/synth_sync_timing.csv`).
- Planted bugs, re-run on the final RTL: the detector always on the I rail fails all three tests; the integrator clamp
  removed fails only the clamp test.
- `make ci` passes: 63 pytest, 27 cocotb.

**Found**

- Test bug, caught by the test's own guard. The first lock input had a 100 ppm clock error, which drifts the
  half-symbol offset by 0.45 symbol over the 4,500-symbol run. That aligns the strobes with no loop at all: the
  no-loop baseline ended at 2.09. Fix: no clock error in the lock run; the clock error stays in the clamp run.
- First synthesis met timing by 0.583 ns: the last Horner rounding, the halving, the add of p1 and the saturation in
  one cycle, 14 logic levels. Split over two stages: +0.745 ns, outputs unchanged. The worst path is now window →
  coefficient adders → Horner DSP.
- My first sidecar draft said ki·e takes two DSPs. The synthesis DSP report says four DSPs carry the six Horner
  products, and ki·e is one DSP with the integrator add folded in. Corrected before committing.
- The README's planted-bug count (15) didn't match its list (13 entries, without the Costas RTL's three). Added the
  sync RTL bugs to the list; the count is now 18, from the list.

## 2026-11-05 (continued): Phase C, sync chain RTL and the first frames out of RTL

**Done**

- `rtl/sync/sync_top.sv`: `sync_rrc` → `sync_agc` → `sync_costas` → `sync_timing`, loop gains as ports.
- `tb/cocotb/test_sync_top.py` (`make sim`): 12,000 bit-true DDC samples (6 dB OQPSK, 1 kHz + 30 Hz/s before the
  coarse estimate, 0.37 symbol, 20 ppm), loops from reset. Random input gaps; output ready 0.8% of the time.
  6,750 + 1,686 outputs bit-exact. 62 clocks/sample (6.3×, set by the RRC) (`data/results/sync_top_rtl_sim.csv`).
- `tb/cocotb/test_sync_top_full.py` and `make sim-full` (was a placeholder): 3 frames, 87,388 samples from reset,
  49,156 outputs bit-exact. The RTL's soft symbols decoded with `receiver.decode_soft()` give 1 CADU, which matches a
  sent frame, and 0 wrong. **First frames out of RTL.** 3 min 40 s in Verilator. Recorded by
  `make sync-rtl-results` (`data/results/sync_chain_rtl_decode.csv`).
- OOC at 100 MHz: chain WNS +1.431 ns, 1,998 LUT, 2,659 FF, 22 DSP48E1, 1 RAMB18 (`synth_sync_top.csv`).
- Planted bugs, all on the final RTL: each inner `tready` link of `sync_top` tied high (3, caught by the chain test
  only), and the two timing bugs from before (still caught).
- `make ci` passes: 63 pytest, 29 cocotb.

**Found**

- The first chain test had the sink ready half the time. A planted AGC ignoring the Costas loop's `tready` passed it.
  The RRC makes a sample every 62 clocks and the stages behind it drain in a few, so no stall ever reached an inner
  link. With the output ready 0.8% of the time (0.5 outputs per 62 clocks, against ~0.56 made), the output is the
  bottleneck and all three link mutants fail.
- The chain's first OOC build met timing by +0.525 ns, on the timing block's coefficient adders into the Horner DSP:
  0.22 ns worse than that block alone. Split into partial sums, then coefficients: chain +1.431 ns, block +1.604 ns,
  one more clock per output (9.42 clocks/sample), outputs unchanged. Vivado now puts the ×3 of c3 in a DSP pre-adder
  (9 DSPs, up from 7, with 186 fewer LUTs).
- After that change, the slow-sink chain test lost its last 2 of 6,750 outputs: `run_stream` waited a fixed 200
  clocks after the input ended, at ~125 clocks per output. The drain window is now a parameter, scaled by the chain
  test to the sink's rate. That's a harness bug; it had passed earlier only because of where the random stalls fell.
- My first `timeout_time` on the long test was in "min", which cocotb rejects. It's simulated time anyway, and no
  other test sets one, so it was removed.
- The README's "15 written up" bug count had been stale since the last session (16 rows); it now comes from the table.

## 2026-11-05 (continued): always-loaded docs trimmed

- CLAUDE.md 698 → 202 lines (41.0 kB → ~14 kB). The detailed spec (§1 kit detail, §2–4, planned §6 targets and CI,
  §8–11) moved verbatim to `docs/buildplan.md` (not imported), keeping the section numbers so the `CLAUDE.md §N`
  references in code and docs still resolve. A script checked that every moved line is in buildplan.md; the
  condensed lines were reviewed by hand. That review caught the required-ADR list deleted by mistake (restored).
- New rule in CLAUDE.md: CLAUDE.md ≤ 250 lines, `progress.md` ≤ 150, trimmed at the end of every session that edits
  them.
- `progress.md` 119 → 67 lines: per-block measurements cut (they're in the README Results table and the CSVs), stale
  clang-tooling step removed (installed, in `make ci`).
- Pointers updated: README (traceback-depth guideline → buildplan §3.6), `signal-spec.md` ("Differences from the
  build plan").

## 2026-11-05 (continued): Phase C lock time, lock range, Doppler tracking, constellation GIF

New `analysis/sync_lock_study.py` (`make sync-lock-study`, ~3.5 min). It runs on the bit-true chain, which the RTL
matches bit for bit, from reset, at 6 dB with a 30 Hz/s ramp, seeds 1–4. Lock means the 10 ms average of the Costas
register stays within 10 Hz of the true residual until the end of the run.

- **Lock range with the host coarse estimate:** −15 to +14 kHz all lock, in 16–35 ms, with 10 of 12 frames decoded;
  +16 and −20 kHz don't. The limit is the estimator's search window (|4f| < 4 × `costas_max_hz`). The estimate always
  leaves 12–18 Hz, which is the 30 Hz/s ramp across its 1 s window, not a bias.
- **Costas pull-in alone:** 0 Hz 19–21 ms; ≤ 100 Hz under 160 ms; 150 Hz 238–314 ms; 200 Hz 377–587 ms; 300 Hz
  0.9–1.2 s, and one seed never locked in 1.37 s.
- **Doppler tracking:** 4.6 s falling through zero at 30 Hz/s gives 0.84 Hz rms error (3.0 Hz max) after 0.1 s, with
  38 of 40 frames decoded.
- Even at zero error, 2 of 12 frames are lost. Checked on seed 1: frame 0, whose sync marker arrives during
  pull-in, and frame 11, at the end of the capture.
- `make plots` now also writes the lock-time and Doppler plots and the constellation GIF (Pillow, from the
  matplotlib install). At 6 dB the clusters were too diffuse to read at GIF size, so the GIF uses 15 dB and a
  150 Hz miss, and says so in its title.
- First attempt sized the run as "6 frames = 1.36 s"; a frame is 0.114 s (8,192 symbols at 72 ksym/s), so 6 frames
  was shorter than the coarse estimator's 1 s window. Now 12 frames.

## 2026-11-05 (continued): Phase D, Viterbi decoder RTL

Built in the build plan's order, each step bit-exact against `model/viterbi_fixed.py` before the next. To give the
unit tests model code to check against, the model's branch metric and modulo select became two functions
(`branch_metric()`, `acs_select()`); `acs()` calls them. The 56 model tests pass unchanged.

- `fec_bm` + `fec_acs`: the branch metrics are checked on all 256 symbol pairs; the ACS on 20,000 random inputs plus
  every difference around 0 and ±256. Branch 1 wins when m1 − m0 is negative as a 9-bit signed number.
- `fec_acs_array`: one step per clock; the trellis comes from the G1/G2 taps, so no table. Every decision row matches
  at 0 dB, 6 dB and on full-scale input. 1,546 LUT, no DSP, WNS +1.552 ns.
- `fec_traceback`: a 256 × 64 ring (1 RAMB36), walking back from state 0 at depth + 3 clocks per bit. Bit-exact at
  depths 96 and 35. 77 LUT, WNS +4.040 ns.
- `fec_viterbi`: at 1.5 dB it makes 93 errors in 3,904 bits, the same bits as the model. 96 clocks per bit, so
  14.5× real time. 1,621 LUT, 1 RAMB36, WNS +1.895 ns. The worst path is the stall enable to the 576 path-metric
  flip-flops (92% routing), not the ACS.
- 12 planted bugs, all caught (README list). Notes:
  - The ACS array ignoring an output stall passed the full-rate run; only the backpressure runs catch it.
  - My first "carry lost" mutant was not a bug: SystemVerilog sizes the operands of `5'(a + b)` to 5 bits, so the
    carry survived and the test rightly passed. The real mutant, `4'(a + b)`, fails.

**Found**

- The first spread guard (> 100 at 0 dB) failed at 65: noise shrinks the path-metric spread. The widest spread
  comes from full-scale clean input (120, against ADR 0006's bound of 180), which is now its own run.
- The wrap check is a lower bound (every path gains at least the step's smallest branch metric). On full-scale
  input that bound is 0, so the check runs only on the noisy runs, where it proves at least 51 wraps.
- Correction: earlier this session I said someone else had edited `analysis/synth_report.py`. It was my own
  `ruff format analysis/`, a formatting-only change, still uncommitted.

## 2026-11-05 (continued): Phase D, streaming frame-sync model (ADR 0010)

The float frame sync looks a frame ahead and back, which hardware can't. `model/framesync_fixed.py` is the causal,
bit-true version the RTL will match (9 tests). `receiver.decode_soft()` now calls a new `decode_frames()`, so both
frame syncs share one back end. `make framesync-study` compares them on the bit-true chain.

**Found**

- First threshold, normalized by a trailing 4,096-symbol mean |v|: while the AGC was still rising after reset, the
  window held the quieter past. 4–14 false peaks filled the verify queue, and the first 2 frames were lost.
  Normalizing by Σ|v| over the correlation's own 52 symbols fixed it.
- Dropping the frame that only verifies cost one frame per acquisition. A one-frame delay line in front of the
  Viterbi (needed anyway) brings it back.
- Seed 1 lost 4 frames at 2.0, 2.5 and 3.0 dB alike. The same loss at every SNR pointed to an event, not noise: at
  frame 20 the timing loop dropped one sample, moving the ASM by one symbol, under another phase hypothesis. A first
  fix that only switched hypothesis at the same position did nothing (0 slips). Following a peak within ±2 symbols
  fixed it: the streaming model now decodes ≥ the float model's frames in all 15 runs (27 vs. 25 on that seed at
  2.0 dB).

## 2026-11-06: Phase D, frame sync RTL (ADR 0010 amendment)

`rtl/fec/`: `fec_soft_quant` (serial 4-bit stream), `fec_fs_correlator`, `fec_fs_fsm`, `fec_fs_window`, and
`fec_framesync` on top. The model gained `windows()`, what the RTL sends the Viterbi. The stimulus is shared by the
model and RTL tests (`model/tests/framesync_stimulus.py`). 13 cocotb scenarios (59 windows, 492,768 pairs) and a
128k-ring FIFO-stall build match the model window for window (`framesync_rtl_sim.csv`). OOC: 100 MHz met, WNS +0.653 ns, 3,112 LUT, 3,066 FF, 4 RAMB36, 1 DSP48E1.

**Decided:** each frame goes to the Viterbi as its own window [s − 128, s + F + 192), read by address from a
32,768-symbol ring (ADR 0010 amendment). ADR 0010's 2-RAMB36 delay line was too short: the first frame of an
acquisition is confirmed ~F + 65 symbols after it starts, and the Viterbi needs run-in and run-out around it.
POST = 2 × depth flushes the frame's last bit inside its own window (model test: the window decodes to the sent
frame, under every hypothesis).

**Found**

- Ring overwrite. Symptom: SVA `a_read_in_ring` fired in the flywheel test, reader at 49,024 with the writer at
  81,987. Root cause: consecutive windows overlap by PRE + POST = 320 symbols, so the next window in the FIFO starts
  before the reader's position, and the guard protected only the reader. Fix: guard both. Clean frames at a fast
  sink hadn't shown it; the reader is slower than a p_valid ≈ 1 input.
- Timing, −1.867 ns: threshold multiply (DSP) → compare → FSM decision → 32-bit subtract → descriptor FIFO in one
  clock. Fix: register the hit flags on the input enable, so the FSM judges one symbol later and nothing else
  changes. Then −0.916 ns: `s_tready` sat in a loop, FIFO head → ring-room subtract → `s_tready` → beat → FSM →
  FIFO write. Fixes: the FSM emits the window's first symbol (start − 140 in its one subtraction), and `s_tready` is
  a register, computed from the FIFO's next count and the ring room with one symbol of margin. +0.653 ns.
- Mutation campaign: 3 of 20 planted bugs first slipped through, each a test gap. (1) With a 64k ring the ring
  still stalled first, so removing the FIFO-space check changed nothing; the FIFO test now uses a 128k ring.
  (2) Slip order +1 before −1 needs peaks at both: `ambiguous_slip()` blends two hypotheses' patterns at e ± 1.
  (3) The early-frame boundary off by one needs a frame exactly there: two hypothesis tests lead with 128 and 127
  symbols. Rerun after the timing changes, with 2 more mutants for the registered `s_tready`: 21 of 22 caught. The
  22nd, FIFO space computed without this clock's pushes, is equivalent: pushes are at least ~F symbols apart (the
  verify pair lands in one clock), so a count one clock late never lets a second push through.
- `quantize(-x) != 15 - quantize(x)` at exact step multiples, but 15 − u is the exact negation of the level the
  correlator and Viterbi use. Derotation is defined on levels (`undo_levels()`), with a test.

## 2026-11-06: Phase D, the chain through the Viterbi

`rtl/top/rx_chain.sv`: `sync_top` → `fec_soft_quant` → `fec_framesync` → `fec_viterbi`. The model gained
`framesync_fixed.decode_windows()`: the RTL Viterbi has no reset between windows, so each window starts from the
metrics the previous one left, and the model now decodes them the same way. `make sim-full` gained
`test_rx_chain_full` (~9 min alone): five synthetic frames from a cold start (`sync_chain.py`, 6 dB, 1 kHz + 30 Hz/s,
20 ppm), 145,642 samples, 4 frames found, 3 windows, 24,960 bits bit-exact with the model chain, 3 of 3 frames equal
to a frame sent after NRZ-M and derandomizing, before RS (`rx_chain_rtl_decode.csv`). OOC: 100 MHz, WNS +0.827 ns,
6,750 LUT, 6,436 FF, 23 DSP48E1, 5 RAMB36 + 1 RAMB18 (`synth_rx_chain.csv`); no new synthesis warnings.

**Found**

- A fast sink never stalls this chain either (CLAUDE.md §12): the Viterbi drains windows faster than symbols arrive,
  so the ring never filled. `run_stream` can now hold the sink until the input has been refused 2,000 clocks (sync_top
  alone refuses ~62), and hold again every 20,000 clocks while input remains.
- Planted quantizer bug (I/Q toggle without `tready`) passed with four frames, one hold, and still with 42 re-holds.
  Root cause: the ring can't fill before the input is 32,768 symbols past the oldest pending window (~49,000 here),
  and the last checked window ended at 49,368, so the stalls reached almost no checked data. Fix: five frames, so
  the third window (49,048–65,752) carries ~40 stalls; the bug is then caught at bit 17,611. The test asserts ≥ 20
  stalls. Also caught: Viterbi reset at each window end, frame sync ignoring the Viterbi's `tready`.
- Model: a 4-symbol run-in decodes clean frames after a slip-back but not after a loss of lock, where the next window
  jumps a frame ahead; only the lock-loss test catches it.
- Open for Phase E: the window flags (`tuser`) and boundary (`tlast`) end at the frame sync; the Viterbi doesn't carry
  them.

## 2026-11-06: Phase D, path-metric formal, 3-bit area, docs/viterbi.md

**3-bit area.** `make synth-ooc` takes `GENERICS`/`NAME` now. The 3-bit decoder: 1,365 LUT, 630 FF, WNS +2.628 ns,
against 1,621 / 694 / +1.895 ns at 4 bits (`synth_fec_viterbi_3bit.csv`). 4-bit stands (ADR 0005 amendment).

**Formal** (`tb/formal/fec_acs_array.sby`, `make formal`). The ADR 0006 bound is SVA in `fec_acs_array.sv`. Proven: a
stall changes no metric. Bounded: no violation within 8 steps of reset at 4 bits. **Open:**
the unbounded proof; its 4-bit induction had not finished after 6.5 hours (base case 13 min), and the 1- and 2-bit
versions timed out at 2 hours.

- First k-induction failed in 40 s. Symptom: counterexample with `s_tvalid` low for 8 steps, then one step out of
  bounds. Root cause: the metrics hold through a stall, so k cycles of induction can be one state, an unreachable
  one. Fix: the spread proof steps every clock; a separate task proves with free handshakes that a stall changes no
  metric. The spread asserts are left out of that task (`ACS_HOLD_ONLY`).
- Yosys rejects the same assertion label in every generate instance; labels dropped inside the generate.
- Running several tasks of one .sby file in parallel corrupted SBY's status database (`sqlite3.DatabaseError`);
  give each run its own `--prefix`.
- Planted bugs: no metric reset and 8-bit metrics at 4-bit soft are caught in < 30 s. An ACS that keeps the larger
  candidate is not, and shouldn't be: the spread stays bounded under max too (cocotb catches its decisions). A
  sign-extended branch metric breaks the bound, but in the model recurrence even the worst input needs 14 steps
  (1-bit) or 18 (2-bit), beyond the bounded depth; a 20-step 1-bit check reached step 14 in 3.3 hours.
- Model recurrence, worst input at every step: the spread peaks at 4·BMmax (8 at 1 bit, 24 at 2 bits), below the
  6·BMmax bound.
- Written first as 2,016 pair asserts, the bound slowed `test_fec_viterbi` from 26 s to 66 s and pushed `make sim`
  toward its 5-minute budget. Rewritten as one equivalent assert (metrics relative to state 0, max − min ≤ 180: pairs
  that close can't wrap, and the spread grows by at most 30 per step, so a violation shows before anything wraps):
  46 s under the same CPU load. Both planted bugs still caught; `make formal` (hold + 8-step bound) 11.5 min.

`docs/viterbi.md` written: the §3.6 tradeoffs, one per ADR, with the measured numbers.

## 2026-11-07: Phase B, Ethernet-fed DDC top (sim and board build; hardware run pending)

fpga-eth-core joined as submodule `rtl/eth` at `eth-core-v0.2`. New: `iq_udp_ingest` (ADR 0011), `clk_gen_eth`
(MMCM: 100 MHz core, 25 MHz PHY reference), `arty_ddc_eth_top` (MII → eth_rx → udp_rx → ingest → DDC → capture →
UART), `constr/arty_eth.xdc`, `make board BOARD_TOP=arty_ddc_eth_top`, `make eth-check`.

- Board build: WNS +1.495 ns, WHS +0.041 ns at 100 MHz; 1,611 LUT, 2,596 FF, 18 RAMB36 + 2 RAMB18, 6 DSP
  (`board_arty_ddc_eth_top.csv`); 0 critical warnings; the clock interaction report shows only eth-core's two
  crossings, both Max Delay Datapath Only.
- Ingest deadlock. Symptom: `test_iq_udp_ingest` at DEPTH 512 hung (DEPTH 1024 passed). Root cause: a datagram one
  byte too long wrote its 512 samples, the ring was full, and `s_tready` refused the surplus byte carrying `tlast`,
  which is what triggers the rewind. Fix: only bytes that write a sample wait for room. Test timeouts added so a
  deadlock fails instead of hanging.
- Mutants. Ingest: 6/6 caught. Top: 3/3, but "ingest reset tied off" was missed at first, because Verilator starts
  flops at 0, so one replay from power-up can't tell. The test now replays twice across a RESET, which is the board
  flow, since opening the serial port resets it.
- A comment starting "Verilator ..." is parsed as a pragma (BADVLTPRAGMA). `pkill -f <pattern>` killed my own
  shell twice: the pattern was in its command line. Kill by PID.
- `make sim` takes 356 s alone (budget 300 s). Before these changes it took 322 s: the budget was already exceeded,
  and the new tests add ~15 s. `test_fec_framesync` alone is 98 s.
- Hardware run not done: the board was claimed by P2 at 11:27.

## 2026-11-07 (cont.): Phase B on hardware over Ethernet; make sim split

**Result** (`ddc_board_eth.csv`, commit 210e742): 37 of 40 replays of the 65,536-sample snippet bit-exact through
gs-replay → eth-core → iq_udp_ingest → DDC: 1× 8/10, 5× 9/10, 5.6× 20/20. Two campaigns before it (code since
changed, not committed as results): 39/40 and 34/40.

- No dump on a second replay. Symptom: 0 bytes on the UART. Root cause: opening the serial port did not reset the
  design (contrary to the 2026-11-04 note), so the capture was still full. A 5 s wait after the open still got no
  dump. Fix: `eth-check` reprograms the FPGA per replay and waits until the host interface regains its address
  (the link drops for 2.3–3.2 s).
- Wrong dumps with all samples present. Symptom: 1,082 mismatches from output 5; 1,328 from 6; 1,112 from 133;
  1,034 from 13,059. Root cause: whole datagrams reordered before the board. The model fed the snippet with
  datagrams 0↔1, order 2,0,1,3, 1↔2 and 102↔103 reproduces each exactly (the last checked bit for bit against the
  saved dump). Not fixed: the ingest releases datagrams in arrival order by design (ADR 0011). Pinning gs-replay
  with taskset changed nothing (3 of 20 at 5.6×), so it was taken out.
- Lost datagrams (no dump), 6 of 120 replays. Every one came on a link that took ≥ 3.1 s to return after
  programming. A 3 s wait after the link returns did not help. In 15 reprogrammings Windows reported 100 Mb/s
  full duplex every time, but none of those link-ups was slow. Cause open; the board counters (Phase E stats
  packet) or a Windows pktmon capture would settle it.
- `make sim` 356 s with frame sync, so `test_fec_framesync` moved to `make sim-slow`, which `make ci` runs. Not
  re-timed: the machine was at load average 16 from other sessions.

## 2026-11-07 (cont.): Phase E step 1, stats packets; where the replay faults come from

Stats packets (docs/protocol.md type 1) from the board over eth-core TX: 18 counters every 100 ms to the
replay's sender. On hardware they arrived the first time. The counters split the replay faults in two:

- **Reordering, host side.** Faulty dumps with all datagrams present had no Ethernet errors and ingest gap 3 /
  lost 2: one adjacent swap, already wrong on the cable.
- **"Lost datagram" was a board bug.** Symptom: the no-dump replays reported eth_ok ~1.4e8 and eth_ovf_lost ~3e9
  after seconds, RX FIFO high-water 4,095 (depth 2,048), ddc_out 0xFFFFFF. Root cause: eth_rx's RX FIFO comes up
  corrupted at PHY link-up. Reproduced without any replay traffic in 1 of 20 reprograms, again on a 3.1 s
  link-up. The MAC leaves reset 200 ms after programming (eth-core's documented sequence), long before the link
  comes up. Fix: reported to P2 (request 0005: hold the MAC in reset until link-up, via MDIO). Stopgap in the
  top: a level above the depth restarts the MAC only, counted in `mac_restarts`.
- Bugs found on the way, each by a test: `stats_packet` drove TVALID in reset (a sink took a beat while the
  test's second run reset it); the stopgap first counted one event twice (`mac_rst_q` lags a cycle). Verilator
  ignores VPI forces unless the net is marked `/*verilator forceable*/`.
- Result (`ddc_board_eth.csv`, commit 4462a51): 38/40 bit-exact, 2 host reorderings, 0 losses, `mac_restarts` 0.
  All link-ups took 2.1–2.6 s this time, against 2.4–6.8 s in the campaign before, so no corruption occurred and
  the stopgap did not fire: on hardware it is untested.
- `CLAUDE.md` and `progress.md` are no longer tracked (the user's call); history still has them.

## 2026-11-07 (cont.): Phase E step 2, fpga-rs-core

New repo [fpga-rs-core](https://github.com/RodeanAzari/fpga-rs-core) (P3 owns it; P4 consumes it at
`rs-core-v1.0` for KP4). Its ADR 0001 records the architecture: riBM, four codeword stages, pass-through on failure.

- Model first: `model/rs.py` (from this repo) plus `model/hw.py`, the RTL's algorithms stage by stage. Both
  cross-checked against reedsolo 1.7.0 (independent) on CCSDS and KP4 suites: 0..t+2 errors, bursts, first/last
  positions, parity-only, all-zero/all-ones data.
- Forney with riBM's Ω^h: exponent −(FCR + 2t), fitted on reference error values at both codes, then checked on
  every decode.
- The reference's three failure checks (deg > t, roots ≠ deg, re-syndrome) are redundant: removing any one changes
  no result, removing two is caught. The RTL keeps roots ≠ deg alone.
- RTL `rs_decoder`: S1 syndromes, S2 riBM (result 2t + 1 clocks after load), S3 Chien + Forney in output order,
  S4 output; 4 codewords in flight. cocotb at both codes: suite under random handshakes, 12 codewords back to back
  with no input stall and no output gap, output stalls filling every slot, misplaced tlast. 24 planted bugs across
  models and RTL, all caught.
- Test bugs found and fixed (not RTL): a coverage count I had miscounted (9 cases at t, not 10); riBM latency
  expected 2t, really load + 2t; a coroutine race in a cycle count, fixed by sampling at the falling edge.
- OOC 100 MHz, xc7a100t: CCSDS WNS +1.457 ns, 4,142 LUT, 1,766 FF, 1.5 BRAM36; KP4 +1.168 ns, 5,558 LUT,
  2,066 FF, 3.5 BRAM36; 0 DSP (fpga-rs-core `docs/reports/ooc/`).
- Not yet: tag `rs-core-v1.0`; CCSDS consuming it (submodule, deinterleave ×4 wrapper, step 3).

## 2026-11-08: Phase E step 3 closed, receiver chain to CADUs in RTL

`rx_chain` now ends in `fec_frame_extract` → `fec_cadu` (RS from fpga-rs-core). `make sim-full`
(`test_rx_chain_full`, 7 frames, cold start, 6 dB): 6 frames found, 5 CADUs, all 5,120 bytes and 5 status words
equal to `cadu_fixed.cadus_from_windows()`; 5/5 are frames sent; RS 0 corrected / 0 failed; 3 input stalls
(`rx_chain_rtl_decode.csv`). OOC 100 MHz: WNS +0.629 ns, WHS +0.073 ns, 11,247 LUT, 8,348 FF, 23 DSP, 5 RAMB36 +
4 RAMB18, 0 critical warnings (`synth_rx_chain.csv`; was 6,750 LUT / +0.827 ns through the Viterbi).

- Test expectation wrong, not the RTL: symptom `only 3 stalls reached the input` (minimum 4) with every data check
  passing. Root cause: the docstring counted one stall per CADU after the first, but a waiting CADU only reaches the
  input while two frames (the 32k-symbol ring) of input remain; the last CADU's window ends closer to the input's
  end than that. Fix: minimum 3 (CADUs 2–4), reasoning in the docstring.
- Mutant (quantizer toggles I/Q on stalled clocks) caught with 3 stalls: byte mismatch after 3,084 bytes.
- OOC build failed: `module 'rs_decoder' not found` — synth_ooc.tcl globbed `rtl/*/*.sv` only. Fix: read
  `rtl/rs/rtl/` with the package first. Also `NAME ?=` in the Makefile picked up WSL's exported `NAME` (hostname)
  and wrote `RodeanStation.log`; now `=` (command-line override still works).
- `make sim`: all pass, 8 min 54 s, on a machine also running Vivado, sim-full and another project's sims; the
  < 5 min budget needs a quiet-machine re-time (already an open question).

## 2026-11-08 (cont.): Phase E step 4, the whole receiver on the board

`arty_rx_eth_top`: eth-core RX → ingest → DDC → `rx_chain` → `cadu_packet` + `stats_packet` → `pkt_arb2` (new:
whole-packet round robin, eth-core has no arbiter) → `udp_tx`. Loop gains etc. from `rx_config_pkg.sv`, generated
by `gen_rtl_tables.py` (staleness-checked); NCO word per recording via `BOARD_GENERICS` (`board_rx.py freq-word`).
Stats fields 18–24 appended (`cadus_sent`, frame-sync counters, `flag_ovf`, `len_err`).

- Sim (`make rx-top-rtl-results`, ~5 min): 1,137 datagrams at line rate (5.69×), 3/3 CADU packets bit-exact,
  501 stats packets intact, 0 loss, eth_rx FIFO high-water 1 B (`rx_top_rtl_decode.csv`). Planted bugs caught:
  `cadus_sent` counting stats packets; NCO word negated (0 CADUs). A first try at the latter (DDC on the default
  word, parameter unused) only tripped Verilator's UNUSEDPARAM: not a test result, replaced.
- Board build: WNS +0.580 ns, WHS +0.007 ns (DDC ingest → mixer), 13,543 LUT, 7 RAMB36 + 8 RAMB18, 29 DSP, 0
  critical warnings (`board_arty_rx_eth_top.csv`).
- **First decode on hardware.** Synthetic recording (300 CADUs, 8 dB): first replay 298 CADUs, 297 matching truth,
  4 codewords failed, ingest_gap 12 (host reordering). Campaign (`board_rx_eth.csv`): 15/15 replays at 1×, 5×,
  5.6× give 298/298 matching, 0 codewords failed; RS corrections 0 whenever ingest_gap = 0, 9–84 otherwise. The
  reorderings are the only damage; a reordering buffer in the ingest would remove it.
- Bugs on the way: `ddc_comp_fir.sv` listed twice in the top's sim sources (DDC and RRC share it: MODDUP); the
  rx_config_pkg linted alone fails UNUSEDPARAM (inline waiver in the generated file); `board_rx.py check` first
  wrote one row per call, losing the first replay's row (now one row per replay in one call).
- Open: `board_arty_ddc_eth_top.md` still has a `[TBD]` interpretation (from 2026-11-07).

## 2026-11-08 (cont.): BER campaign groundwork; ingest reorder buffer

Tagged `v0.4-rs` (whole receiver decodes on the board). `v0.2-sync-lock` and `v0.3-viterbi` don't exist yet:
Phases C and D wait on a real recording and hardware BER, so the tags are out of order.

- Why the reorder buffer first: host swaps (ingest_gap 3–21 per replay at 5×) each corrupt 0.5 ms of signal;
  RS corrections were 0 in every replay without swaps. For BER that is a floor of ~1e-5–1e-4 pre-RS. The user
  chose the RTL fix (ADR 0013) over discarding replays or fixing the host.
- `iq_udp_ingest`: 4 slots by seq, released in seq order; loss skipped once a datagram 4 ahead arrives; late and
  duplicates dropped (`ingest_late`, stats field 25; stats version 2). Bugs on the way: `dist` is an SV keyword;
  my hand-computed gap count (6) was wrong, the model's 9 right; the old drain window (sized for 2 slots and a
  fast sink) timed out at 4 slots with a half-speed sink; the late-datagram test first let a planted bug pass at
  4 slots (the repeat arrived while its slot was still full), reworked so the slot has drained.
- `fec_cadu RS_WRITEBACK = 0`: CADUs leave pre-RS with the RS status, for the Viterbi-only curve. A first planted
  bug (parameter ignored) only tripped Verilator's UNUSEDPARAM; replaced by one that keeps it referenced.
- `scripts/ber_board.py`: 4 cached clean waveforms (modulate() takes ~215 s per 34 s of signal: exact RRC per
  sample) + fresh noise per recording; both builds per recording; Hamming matching to sent frames.
- Board builds: normal receiver WNS +0.224 ns (worst path fec_cadu LUTRAM → RS syndromes, 82% routing; was +0.580
  with the old ingest), 13,597 LUT, 8 RAMB36 + 7 RAMB18. Pre-RS build (`BOARD_SUFFIX=_prers`): `[TBD]`.
- Not run: hardware recheck of the reorder buffer and the BER campaign. The board was held by P7 from 14:10.
- Pre-RS build (`BOARD_SUFFIX=_prers`): WNS +0.093 ns, WHS +0.028 ns (`board_arty_rx_eth_top_prers.csv`).
- **Hardware regression, open.** The rebuilt receiver (reorder ingest) on the board, synthetic recording at 5.6×:
  of 8 replays, 2 clean-ish (298 good with 21 swaps absorbed; 292/297 around one truly lost datagram) and 5 broken
  the same way: `ddc_out` 1,536 (12 datagrams) then the ingest stalls, `eth_ovf_lost` 1,530, `ingest_lost` ~53k,
  `fs_slips` ~1e9 (a counter running every clock), ~7k garbage CADUs (flywheel, RS failed) at a rate above the
  Viterbi's maximum, `pkt_seq` near 2^32, and one 163-byte CADU-typed packet each time; one more replay never
  went quiet. The pre-reorder bitstream gave 15/15 clean the same day. Cause not established. Candidates: a MAC
  restart mid-replay (request 0005 stopgap) resetting the ingest to expect seq 0 while seq ~53k arrives (the
  logger did not print `mac_restarts`); the lower slack of this build; the board state after P7's partial-
  reconfiguration session (P7 held the board 14:10–~15:05). Then the link to the board dropped (169.254.235.36
  gone) and a diagnostic hung; stopped for a physical check. Board released.

## 2026-11-09: reorder-ingest regression, MAC-restart hypothesis tested in simulation

- New `mac_restart_mid_replay` in `test_arty_rx_eth_top_full.py` (make sim-full, ~6 min): the request 0005
  stopgap fired 2,000 clocks into datagram 300 of 1,137 at line rate. The receiver resumes: the cut datagram ends
  as one eth_rx_err, the ingest skips seqs 0–300 (`ingest_lost` 301), eth_ovf_lost 0, the 2 CADUs after the
  restart bit-exact with the model run from datagram 301, frame-sync counters equal to the model's,
  `mac_restarts` 1. Planted bug (ingest reset from the core reset instead of the MAC's) caught: CADU 0 status
  differs (the ingest kept datagram 300's partial samples).
- So a MAC restart alone does not give the board's broken state (fs_slips ~1e9, pkt_seq near 2^32, eth_ovf_lost
  1,530): those values are impossible for the RTL in simulation, like the 2026-11-07 counters P2 flagged in request
  0005. Remaining candidates: the board/link state (the link was down again today: no reply from 169.254.235.36,
  no 169.254 address on the host), or stats packets corrupted on the way. Needs a raw stats dump of a bad case with
  `mac_restarts`, on hardware.

## 2026-11-09 (cont.): runtime NCO word (ADR 0014)

Board held by P2, so off-board work: the NCO word moves from a build parameter to a host command.

- Transport: eth-core's `udp_rx` takes one port, so commands go in-band on the replay port, marked by byte 0 bit 7
  (replay seq never reaches 2^63). SET_NCO = `0x80000001` + u32 word, 8 bytes. New `rtl/io/ctrl_rx.sv` snoops the
  udp_rx → ingest handshake; the ingest ignores commands. Accepted only before the DDC's first sample (same-clock
  check), so a replay sees one word; the word survives a MAC restart. Stats fields 26–28 `nco_word`, `ctrl_ok`,
  `ctrl_bad` (n = 29, version stays 2). Host: `board_rx.set_nco` sends, waits for the stats echo, retries ×5;
  `rx-check` computes the word from the recording; `ber_board.py` sends 0x25C11200.
- Tests: `test_ctrl_rx.py` (new), `test_iq_udp_ingest.py commands_ignored`, `test_arty_rx_eth_top_full.py` now
  builds the top at its 150 kHz default and sets 151 kHz by SET_NCO, plus a refused late SET_NCO; both full tests
  pass (bit-exact, 3/3 and 2/2 CADUs). Planted bugs: 6 in ctrl_rx, 3 in the ingest, 3 in the top, all caught.
  `make sim` 29 runs pass, 4 min 52 s (with Vivado running alongside).
- Bugs on the way: my hand count of ingest gaps (4) was wrong, the model's 6 right (0,2,1,3,5,4,6: every arrival
  after the first is out of sequence). The first ctrl_rx length mutant (check removed) only tripped a Verilator
  unused-signal warning, not a test; a short command after a replay datagram ending in the SET_NCO pattern now
  shows why the length check matters. Testbench: lock_i first changed before the previous datagram's last beat was
  sampled; fixed. ADR draft named a non-existent `sync_doppler.csv` (it is `sync_doppler_track.csv`) and an
  unmeasured Vivado run time; both corrected before commit.
- Board build: WNS +0.256 ns, WHS +0.025 ns, 13,682 LUT, 0 critical warnings (`board_arty_rx_eth_top.csv`). New
  worst path: ingest `seq_q` window compare → `s_tready` → ctrl_rx counter enables (9.4 ns, 48% logic).
- Not done: hardware (board held by P2); the pre-RS build (`_prers`) not rebuilt yet; `gs-replay` (C++) doesn't
  send commands (Python does; Phase F).

## 2026-11-10: gs-replay loopback pacing test de-flaked; per-replay stats dump

- Symptom: `test_speed_and_count` failed 1 run in 5 at load average ~40 (span 70 us under the bound), in 11 of 20
  runs under 24 extra busy loops. Root causes, three: the receiver thread's wake-up time was the arrival time;
  gs-replay itself is preempted before its first sendto and then catches up (span 3–5 ms short with kernel
  timestamps); and loopback reorders datagrams under load (sender migrates CPUs; 2 of 20 runs), which the test
  called a sequence error. Also, flat-out sending reached a span of 1.02x the ideal under load: the old lower bound
  could pass an unpaced sender.
- Fix (test only, gs-replay unchanged): kernel arrival times (SO_TIMESTAMPNS); pacing checked as "no packet before
  its deadline after the process launched" (the pacer's guarantee, which lateness can't break); stream checked by
  sequence number, not arrival order; upper bound 1.1x + 50 ms (a stall is absolute: 22 ms seen at 4x). The upper
  bound is looser at 4x (91 ms, was 55 ms) and tighter at 1x (0.60 s, was 0.75 s); it still catches --speed ignored.
- Evidence: 0/30 failures under the same load, 0/10 without. Planted bugs in gs_replay_main.cpp: pacing skipped
  (packet arrives 448 ms early), speed doubled (246 ms early), speed ignored (span 0.150 s vs 0.037 s): all
  caught. A first "sleep removed" mutant didn't compile (-Werror): not a result, replaced.
- Theil–Sen slope tried first and dropped: under load the 4x pacer falls behind and catches up in bursts, so its
  slope (0.31–1.07 of the period) overlaps flat-out's (0.29–0.59).
- `board_rx.py --dump` / `make rx-check DUMP=DIR` (c2538dc): every stats packet and malformed packet per replay,
  for the reorder-ingest regression.
- Pre-RS build (`_prers`) killed by Claude Code under memory pressure while writing the bitstream (routing done,
  WNS +0.074 ns); partial reports reverted; `build/board/arty_rx_eth_top_prers.bit` is still the stale 2026-11-08
  one (no ctrl_rx: `set_nco` fails loudly on it).

## 2026-11-10 (cont.): Phase F started: board packet parsers in C++; pre-RS build

- Pre-RS bitstream rebuilt (`eceeae2`): WNS +0.074 ns, WHS +0.027 ns, 13,681 LUT, 0 critical warnings; worst
  path MAC reset fan-out into the RRC history registers (94% routing, 0 logic levels). Interpretation written.
- `gs/include/gs/board_packets.hpp`, `gs/src/board_packets.cpp`: header, CADU, stats parsers; explicit big-endian,
  no allocation, the CADU a span into the datagram. Accept/reject as `scripts/board_rx.py` / `board_stats.py`.
- Tests: 21 new GoogleTest cases (hand-built packets incl. the 163-byte CADU-typed one of 2026-11-08), plus
  RTL-sent packets: `test_arty_rx_eth_top_full.py` with `CAPTURE_DIR` saves its 3 CADU packets and 3 stats packets
  with the reference parsers' values (`gs/tests/data/expected.txt`). Release and Debug (ASan/UBSan): 31/31.
- `make fuzz` (was a stub): libFuzzer + ASan/UBSan, seeds from `gs/tests/data`, invariants checked (CADU size and
  view offset, corrections range, stats length, never both types). 60 s: 7.0 M runs, no finding.
- Planted bugs: alternate/swap swapped, be32 byte order, failed codeword with a count accepted, reserved byte 7
  unchecked, CADU view at byte 16: all caught by GoogleTest. Field count uncapped (n > 29): Debug aborts on
  libstdc++'s span bounds assertion, and the fuzzer finds it on its own within 30 s. My mutation loop first
  reported that one as "31 passed": its output filter missed the abort; rerun by hand.
- clang-tidy findings fixed, not suppressed: array subscripts by variable (now span views), swappable test-helper
  parameters (template width, designated-initializer struct), string concatenation (std::filesystem::path).

## 2026-11-10 (cont.): space packets: spec, models, gs-rx

- `docs/signal-spec.md` "Frame layers above the CADU", read from SatDump 1.2.2 (7aef0fe, cloned for reading):
  VCDU header, 2-byte insert zone, 11-bit first header pointer at bytes 12-13, 882-byte zone from byte 14, VCID 5,
  RS-failed CADUs dropped (`rs_usecheck`), and what SatDump's demuxer doesn't check (counter gaps, length vs
  pointer: one stray byte, `demuxer.cpp:103`). First draft cited line numbers off a concatenated listing (vcdu.cpp,
  demuxer.cpp offset by 23 and 37 lines); checked against the files and corrected before commit.
- ADR 0015 (user's choice): drop and count damaged packets; identical to SatDump on unbroken streams.
  `model/space_packets.py`: `mux`, `satdump_demux` (statement-by-statement port), `demux`. Finding while testing
  the port: SatDump emits a packet that starts at a zone's pointer and ends at the zone's end only with the next
  CADU, so a recording's last such packet is never emitted (now in the spec). Testbench bugs on the way: expected
  lists recomputed the idle fill for a shorter packet list; the SatDump flush CADU copied the last CADU's VCID.
- C++: `SpaceDemux` (header-only, fixed 64 KB packet buffer) vs 9 model scenarios (`gs/tests/data/demux`,
  `scripts/gen_gs_vectors.py`, staleness pytest). `SpscRing` (lock-free, slots written in place): 2 M items across
  two threads, ThreadSanitizer build in `make gs-test`. `RxProcessor` + `gs-rx` (network thread -> ring ->
  processing; `cadus.bin`, `packets.bin`, summary to stdout and `gs-rx.txt`). Loopback test: board packets from a
  `mux` stream with one RS-failed CADU, one pkt_seq gap, a stats and a malformed datagram; files equal the models'.
- Planted bugs: demux 7 (5-bit VCID mask passed until a VCID-37 stream was added), ring 4 (two memory-ordering bugs
  caught only by TSan; a never-freed slot hung the test until deadlines were added), gs-rx processing 3, demux
  fuzzer 1: all caught. Two mutants first didn't compile (-Werror) and one mutation loop's grep matched the test's
  own source lines: those were not results, rerun.
- `make fuzz`: two targets (board parser 2.6 M runs, demux 373 k runs, 60 s each), no findings. Not in CI yet.
- Not done: gs-rx on a real board stream (board held by P2); `gs-diff`, `gs-view`.

## 2026-11-10 (cont.): gs-diff (CADUs) and packet_diff (space packets)

- Scope (user's choice): `gs-diff` in C++ compares CADUs only (buildplan §8.5); `scripts/packet_diff.py` compares
  gs-rx's packets with `satdump_demux` over SatDump's .cadu (SatDump 1.2.2 writes no packets). ADR 0015 amended.
- `gs-diff OURS SATDUMP`: frames matched by (VCID, VCDU counter); pass = at least one common frame and every
  common frame's bytes 4-895 equal; ASM and parity differences counted apart; first divergence as frame, byte,
  bit (0 = MSB); a repeated key or a partial CADU is an input error (exit 2). 8 GoogleTests + 5 CLI tests.
- `packet_diff`: packets keyed by where they start (VCDU counter, zone offset), since the 14-bit sequence count
  wraps within a pass. First version's rules missed two legitimate cases found while planting bugs: a length one
  short (SatDump emits it whole, gs-rx drops it: now explained by the golden model's drops on our CADUs,
  `our_drop`) and a full-length SatDump packet across a gap (the gap check had been masked by the short-packet
  check in every test). A gs-rx packet across a gap of its own was first excused by SatDump's side of the same key:
  now always unexplained. An overlap rule I added for "SatDump swallows the next packet's start" was removed:
  the port cuts a packet in progress at the next pointer, so that can't happen.
- Planted bugs: gs-diff 10/10 caught; packet_diff 14/15 + 1 more after a test with SatDump's last pointer read as
  2047. Survivor: the tail rule's one-zone condition (only reachable with fabricated data).
- Chained onto the gs-rx loopback test: gs-rx's own files against a decode with every CADU: gs-diff PASS with the
  RS-failed and never-sent CADUs listed (5/1020, 5/1030); packet_diff PASS, 3 packets `missing_in_ours`, 1
  `satdump_tail`. First expectation there forgot the tail packet (test was wrong, fixed).
- clang-tidy rejected a `FILE*` reader in gs-diff (owning-memory, stream state): replaced by `std::ifstream`.

## 2026-11-10 (cont.): fuzzing in CI

- `make ci` now ends with `fuzz-ci` (30 s per target = buildplan §6's "60 s fuzz run"; user's go-ahead on the
  recommendation): 64 s locally including the incremental build, 1.6 M runs (board parser) and 266 k (demux), no
  findings. Weekly workflow `fuzz-weekly.yml`: 30 min per target, Mondays 03:00 UTC and on demand.
- CI image: libFuzzer's runtime is in `libclang-rt-21-dev`, which `clang` only recommends; the workflow installs with
  `--no-install-recommends`, so `libclang-rt-dev` is now listed explicitly. Not yet seen running on GitHub.
- Proof it fails loud: board parser's header length check weakened to 2 bytes: `make fuzz-ci` exit 2 at once,
  input written to `build/fuzz/crash-*` (the path both workflows upload on failure). Reverted.
- Crash policy (Makefile comment): fix, then commit the input to the target's seed directory; every run replays
  seeds first, so it becomes a regression test with no extra code.

## 2026-11-11: board: reorder-ingest regression not reproduced; first MAC restarts on hardware; SET_NCO on hardware

- Board free (P1 had it until ~23:30). The host's cable adapter (`enx8cae4caa0ec7`) now has a static 192.168.10.1
  (was APIPA 169.254.235.36); the board (192.168.10.2) learns the host from the replay, so `IFACE=192.168.10.1`.
  The link came up only once our bitstream was loaded (P1's design doesn't drive the PHY).
- `make rx-check SPEED=5.6 x4 DUMP=build/dump`, then the full 15-replay campaign (1/5/5.6×) on the current build
  (reorder ingest + ctrl_rx): **19/19 replays, 298/298 CADUs bit-exact, 0 RS symbols corrected**, ingest_gap 0 in
  every one. The 2026-11-08 "5/8 fail" did not reproduce; cause not established (link/address state then).
  Achieved speeds below target (5×: 3.4-4.2, 5.6×: 5.1-5.5; host load ~7.5).
- SET_NCO's first hardware use: `ctrl_ok` counts it, `nco_word` reads back 0x25C11200 (the computed word).
- Replay 10 (5×): **mac_restarts = 14**, all before the first replay datagram (the board's first stats packet
  already has 14 with eth_ok 1 = the SET_NCO command); the replay then decoded perfectly. First time the request
  0005 stopgap fired on hardware; raw counters sent to P2 in request 0005 (MAC-only restart clears it; counters
  consistent, so a persistently bad RX clock looks unlikely).
- The first 4-replay run overwrote `board_rx_eth.csv` (15 rows of the older build) with 4 rows; rerunning the full
  campaign replaced it properly. Interpretation rewritten; README rows updated (also its stale timing row:
  +0.580 ns from the build before ctrl_rx; now +0.256 ns, 13,682 LUT).

## 2026-11-11 (cont.): gs-view v1 (ADR 0016)

- gs-rx writes `DIR/status.txt` every 0.5 s (fixed-buffer formatter `gs/status.hpp`, POSIX write + rename, no
  allocation on the processing thread); the final summary uses the same formatter. New counters
  `rs_symbols_corrected`, `asm_bit_errors`, `status_write_errors`. `gs-view DIR [--once]` draws board sync, ingest,
  CADUs (FER = RS-failed / CADU packets, rate over two distinct snapshots), FEC, packet counters.
- Tests: 9 GoogleTests (formatter, screen), loopback test now reads the live snapshot mid-run (state=running, every
  datagram counted), the final one (= summary) and `gs-view --once`. Planted bugs: 15, all caught after two fixes to
  the tests: a NaN rate or FER prints "-nan", which the assertions "rate -" / "FER -" matched (now anchored); one
  mutant first didn't compile (unused parameter), redone.
- Found on the way: gs-view polls at gs-rx's write period, so it often reads one snapshot twice: rates are taken
  against the previous *distinct* snapshot.
- Hardware BER campaign running meanwhile (both builds; at 3.0 dB no post-RS error in 7 files so far).
