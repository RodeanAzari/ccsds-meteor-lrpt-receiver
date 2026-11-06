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
