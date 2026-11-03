# fer_full_chain

- **Commit:** `950a988244d0dd72432f974d62e8da0ffc88fea3`
- **Command:** `python -m ber` (module in `analysis/`)
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1
- **Input:** synthetic, seeds 1 to 5, 1 kHz offset, 30 Hz/s ramp, 0.37 symbol timing offset, 20 ppm clock. No real recording.

The whole float receiver recovers every frame it can reach from 2.5 dB up: 190 of 200, where the 10 missing frames are the first and last of each 40-frame run, which have no Viterbi margin. At 2.0 dB it recovers 183, at 1.5 dB 54, and at 1.0 dB none. The signal includes a 1 kHz offset, a 30 Hz/s Doppler ramp, a 0.37-symbol timing offset and a 20 ppm clock error. Synthetic AWGN only: no phase noise, interference or fading.
