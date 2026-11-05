# synth_sync_costas

- **Commit:** `743378e0aa6f35ba5fc467776eb4518f3152302d`
- **Command:** `make synth-ooc TOP=sync_costas`
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1, Vivado 2025.2
- **Input:** synthetic, no input data: out-of-context place and route of sync_costas on xc7a100tcsg324-1. No real recording.

The Costas loop closes timing out of context at 100 MHz on the xc7a100t-1 after place and route, with 2.360 ns setup and 0.174 ns hold slack and no failing endpoints. It uses 7 DSP48E1s (the four rotator products, the two loop-gain products, and one in the frequency/phase path), 469 LUTs, 153 flip-flops and one RAMB18, its own copy of the DDC's quarter-wave sine table. The first version computed the phase detector (two conditional negations, a subtract and a clamp) in one cycle and met timing by only 0.512 ns; splitting it over two stages raised the slack to 2.360 ns for one more clock per sample, without changing any output. The worst path is now the ki·e product into the frequency integrator's add and clamp (7.64 ns). Out-of-context results exclude I/O and clocking.
