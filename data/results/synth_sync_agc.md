# synth_sync_agc

- **Commit:** `fac2e4ca30e1cb1144e93774fb231697d0e43469`
- **Command:** `make synth-ooc TOP=sync_agc`
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1, Vivado 2025.2
- **Input:** synthetic, no input data: out-of-context place and route of sync_agc on xc7a100tcsg324-1. No real recording.

The AGC closes timing out of context at 100 MHz on the xc7a100t-1 after place and route, with 2.344 ns setup and 0.227 ns hold slack and no failing endpoints. It uses 4 DSP48E1s (the gain multiply on each rail and the two squares for the power detector), 163 LUTs and 68 flip-flops; the pipeline registers were absorbed into the DSPs. The worst path is the gain register into the gain multiplier (6.98 ns). Out-of-context results exclude I/O and clocking.
