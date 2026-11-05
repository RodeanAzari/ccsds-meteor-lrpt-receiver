# synth_sync_rrc

- **Commit:** `38e39f0f8ac16cea6eb00d5d5a6a0c396596064a`
- **Command:** `make synth-ooc TOP=sync_rrc`
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1, Vivado 2025.2
- **Input:** synthetic, no input data: out-of-context place and route of sync_rrc on xc7a100tcsg324-1. No real recording.

The RRC matched filter closes timing out of context at 100 MHz on the xc7a100t-1 after place and route, with 2.453 ns setup and 0.107 ns hold slack and no failing endpoints. Both multipliers (one per rail) landed in DSP48E1s. The worst path runs from the accumulator through rounding and saturation into the output register (6.73 ns). The 1,874 flip-flops are mostly the 57-sample history on both rails (1,824 bits); the 57 taps sit in LUTs, not BRAM. An SRL or BRAM history would shrink the flip-flop count if area ever mattered; at 1.0% of the LUTs it does not. Out-of-context results exclude I/O and clocking.
