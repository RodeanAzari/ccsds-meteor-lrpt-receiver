# ddc_board_ila_iq

- **Commit:** `40f4d4feac92fc6c91ecabbca3884f574d926df1 (with uncommitted changes)`
- **Command:** `PYTHONPATH=. python scripts/ddc_board.py ila-check build/board/ila_ddc.csv`
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1
- **Input:** synthetic, snippet seed 2026, 8.0 dB, carrier 151 kHz (scripts/ddc_board.py), played from BRAM on the Arty A7-100T, DDC output captured by the ILA. No real recording.

The first 512 DDC outputs (2 ms at 256 kS/s) from the ILA capture, next to the bit-true model's, for the plot `docs/media/2026-11-04_phase-b_ddc-ila-baseband.png`. Board and model columns are identical. The first 7 outputs are exactly zero, and the next few are small, while the CIC and compensation FIR fill. The model shows the same. The signal is still unsynchronized, with a 1 kHz residual carrier and no timing recovery, so the I/Q scatter is a noisy ring rather than four clusters. The clusters come in Phase C.
