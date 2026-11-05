# ddc_board_spectrum

- **Commit:** `8f4076e7cbd4bc043182006192247922e7db47e9`
- **Command:** `PYTHONPATH=. python scripts/ddc_board.py check /dev/ttyUSB1`
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1
- **Input:** synthetic, before: the ROM snippet (cu8 - 127.5, 1.024 MS/s); after: the board's DDC output (s16, 256 kS/s); Welch, 1024-point segments, no detrending; seed 2026. No real recording.

Spectrum of the bring-up snippet before the DDC (cu8 minus 127.5 at 1.024 MS/s) and of the DDC output captured from the board (s16 at 256 kS/s). Before: the signal sits at +151 kHz and the DC offset added to the snippet shows as a spike at 0 Hz, the highest point of the spectrum. After: the signal is centred at +1 kHz (the residual between the 151 kHz carrier and the 150 kHz NCO, as a Doppler residual would be) and the DC spike is gone. The output's rounded shoulders are the compensation FIR's stop band from about 70 kHz, followed by the anti-alias roll-off. Each panel is normalized to its own peak, so the two vertical scales are not comparable in absolute terms. Welch PSD with 1024-point segments and no detrending (detrending would hide the DC offset).
