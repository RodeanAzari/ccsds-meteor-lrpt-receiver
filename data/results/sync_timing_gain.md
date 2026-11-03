# sync_timing_gain

- **Commit:** `950a988244d0dd72432f974d62e8da0ffc88fea3`
- **Command:** `python -m sync_study` (module in `analysis/`)
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1
- **Input:** synthetic, seeds 1 to 4, 1 kHz offset, 30 Hz/s ramp, coarse estimate applied, Costas at the default bandwidth. No real recording.

The timing loop is insensitive to its gain: kp from 0.005 to 0.04 (ki = kp^2/4) all decode 77 to 80 of 88 frames at 2 dB and 88 above that. The default of 0.02 stays. Measured with the Costas loop at its new 0.001 default.
