# synth_ddc_top

- **Commit:** `41efc488a5eeb5a692c24cf2c7e12f103fe2d959`
- **Command:** `make synth-ooc TOP=ddc_top`
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1, Vivado 2025.2
- **Input:** synthetic, no input data: out-of-context place and route of ddc_top on xc7a100tcsg324-1. No real recording.

The DDC closes timing out of context at 100 MHz on the xc7a100t-1 after place and route, with 0.661 ns setup and 0.112 ns hold slack and no failing endpoints. Every multiplier landed in a DSP48E1 (6: four in the mixer's complex multiply, one per rail in the compensation FIR), and the NCO's quarter-wave table is one RAMB18. The whole DDC uses 1.6% of the LUTs. The first run failed by 3.26 ns because the CIC computed integrators, combs, rounding and saturation in one cycle; pipelining the combs (they run at a quarter of the input rate) fixed it without changing any output. The worst path is now the DC-block accumulator in `ddc_ingest` (8.73 ns: update, round, saturate). The margin is thin for when the block sits in a full design with other logic around it; pipelining the DC block's output rounding is the first fix if the integrated build fails. The FIR's 1,033 flip-flops are mostly its 31-sample history shift register on both rails; an SRL or BRAM history would shrink it if area ever mattered. Out-of-context results exclude I/O and clocking; the board-level build is still to come.
