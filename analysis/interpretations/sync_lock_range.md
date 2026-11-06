This is the whole receiver's lock range: the host's coarse estimate (ADR 0002) followed by the bit-true chain from reset.

- **Range: every offset from −15 kHz to +14 kHz locked**, in 16–35 ms, and decoded 10 of 12 frames (the two edge frames, as in sync_lock_costas). +16 kHz and −20 kHz never locked. That is about 4x the ±3.4 kHz Doppler, with room for the tuner's crystal error.
- **The limit is the coarse estimator's search window**, |4f| < 4 × `costas_max_hz` = 60 kHz, not the loops. Outside it the estimate finds no line and returns 0 (the residual column equals the offset). Widening the range means raising `costas_max_hz`.
- **The coarse estimate always leaves about −15 Hz (12.4–18.2 Hz).** The estimate averages over its 1 s window while the carrier rises 30 Hz/s, so at t = 0 the carrier sits about half a second of ramp (15 Hz) below the estimate. It is not an estimator bias. 15 Hz is well inside the loop's fast pull-in (sync_lock_costas: under 50 ms up to 50 Hz).
