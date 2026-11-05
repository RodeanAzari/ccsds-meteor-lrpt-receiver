# ddc_board

- **Commit:** `47fc77bcbd1e937fece6ef728310e885a3554b2e`
- **Command:** `PYTHONPATH=. python scripts/ddc_board.py check /dev/ttyUSB1`
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1
- **Input:** synthetic, snippet seed 2026, 8.0 dB, carrier 151 kHz (scripts/ddc_board.py), played from BRAM on the Arty A7-100T. No real recording.

First hardware result: the DDC running on the Arty A7-100T at 100 MHz produces exactly the bit-true model's output. A 65,536-sample synthetic cu8 snippet (OQPSK frames on a 151 kHz carrier with a 30 Hz/s ramp, 8 dB Eb/N0 and a DC offset) plays from block RAM through `ddc_top` with real backpressure; all 16,384 outputs, read back over the UART with a CRC-32 trailer, match `model/ddc_fixed.py` with no mismatches. The same comparison passed on three board runs, one of which followed a reprogram and one only a port-open reset; the two dumps saved from those runs are byte-identical. The input is synthetic and the clock is the board's 100 MHz oscillator; a real recording and the Ethernet replay path (gated on eth-core-v0.1) are still to come.
