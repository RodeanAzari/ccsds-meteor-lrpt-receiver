# sync_costas_bw

- **Commit:** `950a988244d0dd72432f974d62e8da0ffc88fea3`
- **Command:** `python -m sync_study` (module in `analysis/`)
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1
- **Input:** synthetic, seeds 1 to 4, 1 kHz offset, 30 Hz/s ramp, coarse estimate applied. No real recording.

With the coarse estimate applied, narrow Costas loops do best. 0.0005 and 0.001 rad/sample decode 85 and 79 of 88 at 2 dB and 86 to 88 above that; 0.002 drops to 23 at 2 dB, and 0.008 fails below 6 dB. The default is 0.001: within 7 frames of the best at 2 dB, tied above, with twice the bandwidth of 0.0005 to absorb Doppler rate and coarse-estimate error. Only a 30 Hz/s ramp was tested, against a computed peak of about 31 Hz/s for an overhead pass.
