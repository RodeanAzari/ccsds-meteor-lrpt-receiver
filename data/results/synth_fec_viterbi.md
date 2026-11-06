# synth_fec_viterbi

- **Commit:** `5788939b113a4c7872abb7d06492008153741341 (with uncommitted changes)`
- **Command:** `make synth-ooc TOP=fec_viterbi`
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1, Vivado 2025.2
- **Input:** synthetic, no input data: out-of-context place and route of fec_viterbi on xc7a100tcsg324-1. No real recording.

The whole Viterbi decoder (64-state ACS array plus BRAM traceback) meets timing out of context at 100 MHz on the xc7a100t-1 after place and route, with no failing endpoints (slack in the CSV). It uses 1,621 LUTs (2.6% of the device), 694 flip-flops, one RAMB36 and no DSPs. The ACS array is almost all of it. The worst path is the stall: the traceback's busy flag sets the array's ready, which drives the clock enable of all 576 path-metric flip-flops. It is one LUT level, and 92% of the delay is routing. The add-compare-select logic itself is not the limit. Out-of-context results exclude I/O and clocking.
