# synth_fec_traceback

- **Commit:** `5788939b113a4c7872abb7d06492008153741341 (with uncommitted changes)`
- **Command:** `make synth-ooc TOP=fec_traceback`
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1, Vivado 2025.2
- **Input:** synthetic, no input data: out-of-context place and route of fec_traceback on xc7a100tcsg324-1. No real recording.

The traceback meets timing out of context at 100 MHz on the xc7a100t-1 after place and route, with no failing endpoints (slack in the CSV). The 256 × 64-bit decision ring is one RAMB36, as ADR 0007 planned, and the logic is 77 LUTs. The worst path is the one ADR 0007 predicted: the block RAM's output through the 64:1 select (three LUT6 levels and a MUXF7) into the 6-bit state register. The addresses don't depend on the state, so this is the only path the walk has to close in one clock, and it does with margin. Out-of-context results exclude I/O and clocking.
