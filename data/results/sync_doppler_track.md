# sync_doppler_track

- **Commit:** `0d37302d1453df30736a97eb7c26cdcb117dec4c (with uncommitted changes)`
- **Command:** `python -m sync_lock_study` (module in `analysis/`)
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1
- **Input:** synthetic, seed 1, 40 frames, 6.0 dB Eb/N0, carrier from 70 Hz falling at 30.0 Hz/s; estimate = NCO tune (host coarse estimate) + Costas register, 10 ms average; bit-true chain from reset; 38 of 40 frames decoded. No real recording.

This is the receiver's carrier estimate (NCO tune from the host's coarse estimate, plus the Costas frequency register) through closest approach. The Doppler rate there is the pass maximum, 30 Hz/s, falling through zero over 4.6 s. The run uses the bit-true chain from reset at 6 dB.

- After pull-in (the first 0.1 s), the 10 ms-averaged error is 0.84 Hz rms, with a maximum of 3.0 Hz.
- The first point is 17.8 Hz off, because the coarse estimate averages over the ramp (see sync_lock_range).
- 38 of 40 frames decoded; the two lost are at the capture edges.

The run covers only the steepest few seconds, not a whole pass, because the bit-true model is slow: this 4.6 s run takes about 30 s. The rest of a pass changes more slowly than this segment.
