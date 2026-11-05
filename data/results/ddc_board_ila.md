# ddc_board_ila

- **Commit:** `9393fb55411c9279ba43a2d8ac0e2d4cc9f1f00f (with uncommitted changes)`
- **Command:** `PYTHONPATH=. python scripts/ddc_board.py ila-check build/board/ila_ddc.csv`
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1
- **Input:** synthetic, snippet seed 2026, 8.0 dB, carrier 151 kHz (scripts/ddc_board.py), played from BRAM on the Arty A7-100T, DDC output captured by the ILA. No real recording.

A second, independent readout of the DDC on the Arty, this time through JTAG instead of the UART. The ILA stored only cycles where the DDC output handshook, triggered on the first one after a reset, and held all 16,384 outputs of the 65,536-sample ROM snippet. Every one matches `model/ddc_fixed.py`, with no mismatches. This also checks the capture itself. The parser refuses a window that doesn't start at the trigger, and any stored row that isn't a handshake. Any off-by-one in trigger alignment, or a probe bit out of order, would show as mismatches (`scripts/tests/test_ddc_board.py`). The reset came from opening the serial port, which resets the design on this board (observed; the mechanism is not established). The input is synthetic, at 8 dB Eb/N0 on a 151 kHz carrier. The clock is the board's 100 MHz oscillator.
