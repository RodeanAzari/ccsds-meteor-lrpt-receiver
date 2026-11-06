# 0010: Streaming frame sync: local-normalized 4-bit correlation, verify queue, one-frame delay line, slip following

## Context

The model's frame sync (`receiver.frame_sync()`) is offline. It confirms an encoded-ASM peak by looking one frame
ahead, holds flywheel frames back until lock is confirmed, and after a loss searches again from the last good ASM,
in the past. The RTL sees each symbol once (buildplan §3.5). It needs a causal design that finds the same frames, and
a bit-true model of it before any RTL (CLAUDE.md rule).

## Options considered

1. **Correlator input.** s16 soft symbols, or the 4-bit symbols the Viterbi decoder gets (ADR 0005). 4-bit: one
   stream, and the 52-term sums are adds and subtracts of 5-bit values.
2. **Threshold normalization.** (a) A running mean |v| over a trailing 4,096-symbol window, the causal version of the
   float model's global mean. (b) Σ|v| over the correlation's own 52 symbols.
3. **Verification.** (a) One candidate at a time. (b) A small queue of candidates, each verified one frame later.
4. **The verifying frame.** (a) Drop it: it has passed when it's confirmed. (b) Feed the Viterbi through a
   one-frame delay line, so the frame is still there.
5. **Flywheel frames.** (a) Hold them until the lock is confirmed, as the float model does (a delay of flywheel + 1
   frames). (b) Emit them at once, flagged; RS rejects the ones that are garbage.
6. **Slips in lock.** (a) Treat a slipped ASM as a miss and re-search after the flywheel. (b) Follow any hypothesis
   peaking within ±2 symbols of the expected position.

## Decision

1. 4-bit, levels v = 2u − 15.
2. **(b), local normalization**: |c| · 64 > thr64 · Σ|v|, thr64 = 48 (0.75). (a) was tried first. While the AGC is
   still rising after reset, the trailing window holds the quieter past, so the threshold is too low. It queued 4–14
   false peaks at symbols 4,049–8,064, which filled the queue and cost the first 2 frames.
3. **(b), a 4-deep queue**; a full queue drops the new peak and counts it (none dropped in the study).
4. **(b), a one-frame delay line.** The Viterbi needs symbols from before a frame's start anyway (the model decodes
   from 128 symbols before it). 16,384 × 4 bits is 2 RAMB36 of 135. With it, the first frame of each acquisition is
   decoded too.
5. **(b), emit and flag.** Holding 5 frames costs 10 RAMB36. With (6b), the frames held back were garbage anyway.
6. **(b), follow within ±2 symbols.** On the bit-true chain, the timing loop dropping one sample shifted the ASM by a
   symbol and changed the hypothesis. That cost seed 1 four frames at 2.0, 2.5 and 3.0 dB alike, emitted under the
   wrong phase, until (b) was added.

## Consequences

- One correlator per hypothesis (4 × 52-term add/subtract trees), one Σ|v| tree, a 4-entry queue, a 5-deep history
  of the 4 hit flags (the slip decision comes 2 symbols after the expected position), a 2-RAMB36 delay line.
- The model is `model/framesync_fixed.py`; the RTL must match its frame list exactly.
- Up to `flywheel` frames of garbage per real loss of lock reach RS, flagged; downstream counts must use RS status.
- Not covered: a slip of more than 2 symbols, which the flywheel and a new search handle at the cost of frames.

## Measured evidence

`data/results/framesync_fixed.csv`: the bit-true sync chain from reset, 30 frames, seeds 1–3, 1.5–4 dB. Both frame
syncs feed the same back end. The streaming model decodes at least as many correct frames as the float model in
every run, and the same frame list in 12 of 15. At 2.0 dB on seed 1 it decodes 27 against 25, because it follows the
slip where the float model searches again. Synthetic signals only; not confirmed on a real recording: `[TBD]`.

## Amendment (2026-11-05): what the RTL sends the Viterbi

**Context.** Option 4(b) sized the delay line at one frame (2 RAMB36). Two details missed: the first frame of an
acquisition is confirmed when the correlation one frame later completes, ~F + 65 symbols after its start, and the
Viterbi also needs symbols before and after it. The RTL Viterbi (`fec_viterbi`) is one continuous stream with a
96-step sliding traceback, while the model decodes each frame as its own window.

**Options.** (a) Per-frame windows read by address from a ring: each emitted frame is sent as symbols
[start − 128, start + F + 192), derotated. (b) A continuous delayed stream, with frames only tagged.

**Decision: (a).** Rejected (b): a ±1-symbol slip breaks the symbol pairing, and the overlapping frames a −1 or −2
slip produces can't both be emitted, so (b) can't match the model's frame list. With (a):
- PRE = 128 symbols, the model's 64-step run-in (`receiver.decode_frames()`). POST = 192 symbols = 2 × the traceback
  depth, so a frame's last bit leaves the sliding traceback inside its own window. Without POST it would wait for the
  next frame's symbols, which never come after a loss of lock (`model/tests/test_framesync_fixed.py`).
- The ring holds 32,768 symbols, 4 RAMB36 rather than 2. A window spans 16,704 symbols, plus the ~200-symbol
  decision lag.
- Frames whose run-in would begin before symbol 0 are not emitted, and are counted (`early_o`).
- Cost: windows overlap by PRE + POST, ~2% more Viterbi steps, against 14.5× real-time headroom.
- tuser = {flywheel, swap, alternate} per window; tlast ends it. Downstream (Phase E) takes bits PRE/2 ..
  PRE/2 + 8,191 of each window's decoded output.

**Measured evidence.** `make sim`, `test_fec_framesync.py`: the RTL matches `windows(frame_sync_fixed())` window for
window and pair for pair, counters included, in 13 scenarios (`data/results/framesync_rtl_sim.csv`: 4 hypotheses,
flywheel, lock loss, carrier slip, timing slips −1 and +2, a −1/+1 tie, noise, a full verify queue, ring
backpressure), plus a 128k-ring build that stalls at the descriptor FIFO. OOC: 100 MHz, WNS +0.653 ns, 4 RAMB36.
Synthetic signals only.

