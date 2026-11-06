This is the receiver's carrier estimate (NCO tune from the host's coarse estimate, plus the Costas frequency register) through closest approach. The Doppler rate there is the pass maximum, 30 Hz/s, falling through zero over 4.6 s. The run uses the bit-true chain from reset at 6 dB.

- After pull-in (the first 0.1 s), the 10 ms-averaged error is 0.84 Hz rms, with a maximum of 3.0 Hz.
- The first point is 17.8 Hz off, because the coarse estimate averages over the ramp (see sync_lock_range).
- 38 of 40 frames decoded; the two lost are at the capture edges.

The run covers only the steepest few seconds, not a whole pass, because the bit-true model is slow: this 4.6 s run takes about 30 s. The rest of a pass changes more slowly than this segment.
