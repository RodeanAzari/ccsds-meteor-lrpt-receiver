# rrc_fixed_chain

- **Commit:** `bb4d98d6837a912492f1728cd53f7578f6c1574d`
- **Command:** `python -m rrc_fixed_study` (module in `analysis/`)
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1
- **Input:** synthetic, 2026; bit-true DDC on both arms; ebn0 inf = no noise, cu8 scaled as for 8 dB. No real recording.

The bit-true RRC costs nothing the decoder can see. Both arms use the bit-true DDC; only the matched filter differs. At every Eb/N0 from 2 to 8 dB the receiver decodes the same frames (18 of 20; the first and last frame are the usual loss at the edges) and soft-symbol SNR agrees within 0.01 dB. RRC SQNR, against the same causal 57-tap filter run unquantized on the same integer input, is 63.3–67.6 dB: about 12 dB under the DDC's own 51–54 dB (`ddc_fixed_chain.csv`), so the DDC, not the RRC, sets the quantization floor. Synthetic signal only: 1 kHz offset, 30 Hz/s ramp, 0.37-symbol timing offset, 20 ppm clock error. No real recording.
