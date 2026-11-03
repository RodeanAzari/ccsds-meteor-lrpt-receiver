# ddc_fixed_chain

- **Commit:** `ea90d38c53fb7dbfce2a230411ed2954439b44d8`
- **Command:** `python -m ddc_fixed_study` (module in `analysis/`)
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1
- **Input:** synthetic, 2026; ebn0 inf = no noise, cu8 scaled as for 8 dB. No real recording.

The bit-true DDC costs nothing the decoder can see. At every Eb/N0 from 2 to 8 dB, the receiver decodes the same frames with the bit-true DDC as with the float DDC (18 of 20; the first and last frame of each run are the usual loss at the edges), and soft-symbol SNR agrees within 0.01 dB. With no noise it is 31.2 dB fixed against 31.0 dB float, a difference inside the estimate's spread; that point is limited by the loops, not the DDC. DDC SQNR against a float model of the same causal structure is 51.0–53.7 dB on noisy inputs and 64.1 dB on the clean one. Why SQNR is lower with noise than without is not yet established; it does not reach the soft symbols. Synthetic signal only: 1 kHz offset, 30 Hz/s ramp, 0.37-symbol timing offset, 20 ppm clock error.
