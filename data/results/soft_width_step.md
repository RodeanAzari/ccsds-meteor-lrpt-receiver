# soft_width_step

- **Commit:** `34e431c1304fee45882ac49aeadf49f980839aba`
- **Command:** `python -m soft_width_study` (module in `analysis/`)
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1
- **Input:** synthetic, noise seed from Eb/N0; step = 2^shift / 4096 of rail rms. No real recording.

Quantizer step sweep at 3 dB, both widths, the same noise for every row. Step 2^shift in sync units, where ONE = 4096 is the AGC's rail rms. Both widths are best at shift 10 (step ONE/4). For 4 bits, shift 9 is equal within the statistics (237 vs 228 errors). At shift 12 (step ONE) both widths collapse to the same nearly-hard decision. Each row has at least 100 errors (±20% on BER). AWGN symbol channel; synthetic only.
