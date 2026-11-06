# synth_fec_acs_array

- **Commit:** `949cc5b2f1627393f5841b5d7c49777fb8d1accf (with uncommitted changes)`
- **Command:** `make synth-ooc TOP=fec_acs_array`
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1, Vivado 2025.2
- **Input:** synthetic, no input data: out-of-context place and route of fec_acs_array on xc7a100tcsg324-1. No real recording.

The 64-state ACS array, one trellis step per clock, meets timing out of context at 100 MHz on the xc7a100t-1 after place and route, with no failing endpoints (slack in the CSV). It uses 1,546 LUTs and 641 flip-flops (64 × 9-bit path metrics plus the 64-bit decision row and the valid flag), and no DSPs: 128 small adders and 64 compares fit LUT carry chains better. The worst path is not the add-compare-select. It is the stall enable: the output-valid register drives the clock enable of all 576 path-metric flip-flops, through one LUT level, and 92% of its 7.95 ns is routing. If the array has to get faster, that fanout is the first thing to register or duplicate. Out-of-context results exclude I/O and clocking.
