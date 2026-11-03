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
