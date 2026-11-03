# ber_awgn

- **Commit:** `950a988244d0dd72432f974d62e8da0ffc88fea3`
- **Command:** `python -m ber` (module in `analysis/`)
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1
- **Input:** synthetic, seeds derived from Eb/N0. Theory: Q(sqrt(2Eb/N0)) for uncoded, union bound for Viterbi. No real recording.

The model agrees with theory, which validates the modulator, the noise scaling and the Viterbi decoder. Uncoded waveform BER is within counting error of Q(sqrt(2Eb/N0)) at every point from 0 to 8 dB. Soft Viterbi sits on the union bound from 3.5 dB up, with 1.79e-5 measured against 1.81e-5 at 4.0 dB; below that the bound is loose, as expected. Points with fewer than 100 errors are upper bounds and are left off the plot: Viterbi at 4.5 dB (93 errors) and 5.0 dB. NRZ-M decoding roughly doubles the BER at high Eb/N0 (3.15e-6 against 1.54e-6 at 4.5 dB), because one decoded error becomes two adjacent errors.
