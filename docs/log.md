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
