# sync_fixed_chain

- **Commit:** `48cd29bacd9c5921022c0a03aafab778a815553f`
- **Command:** `python -m sync_fixed_study` (module in `analysis/`)
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1
- **Input:** synthetic, 2026; ramp 30.0 Hz/s, 0.37-symbol timing offset, 20 ppm clock; float arm is the float chain. No real recording.

The bit-true sync chain (DDC, RRC, AGC, Costas, Farrow + per-rail Gardner, all integer) decodes the same frames as the float chain at every point: 18 of 20 from 2 to 8 dB, at 1 kHz and at 3.4 kHz carrier offset (the Doppler maximum), both with a 30 Hz/s ramp (about the physical maximum). The first and last frame are the usual loss at the edges. Soft-symbol SNR agrees within 0.01 dB at 1 kHz. At 3.4 kHz the bit-true chain is 0.04–0.18 dB better. The likely cause, not established: the bit-true chain puts the host's coarse estimate into the DDC NCO (ADR 0002), so the RRC sees a centred signal, while the float chain derotates after the RRC. NCO + Costas frequency tracks the ramp with 1.7–4.0 Hz rms error over the second half of each run. Synthetic signal only, 0.37-symbol timing offset, 20 ppm clock error. No real recording.
