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
