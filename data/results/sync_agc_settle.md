# sync_agc_settle

- **Commit:** `48cd29bacd9c5921022c0a03aafab778a815553f`
- **Command:** `python -m sync_fixed_study` (module in `analysis/`)
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1
- **Input:** synthetic, 2026; AGC from gain 1.0 on the bit-true RRC output, before the coarse NCO correction. No real recording.

The AGC starts at a gain of 1.0 and settles at 5.9–9.7 on the synthetic recording (higher at low Eb/N0, where the cu8 scaling puts less signal in each LSB), far inside its 1/4096–256 range. Reaching 90% of the settled gain takes 59–103 ms, well inside the ~1 s the coarse estimate already uses, so the AGC does not lengthen acquisition. Settled gain is the mean over the second half of the run. Synthetic only; a real recording's level is `[TBD]`.
