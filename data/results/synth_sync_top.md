# synth_sync_top

- **Commit:** `84859c45331e5afe8f0bab5fae9c0974dcaee50c (with uncommitted changes)`
- **Command:** `make synth-ooc TOP=sync_top`
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1, Vivado 2025.2
- **Input:** synthetic, no input data: out-of-context place and route of sync_top on xc7a100tcsg324-1. No real recording.

The whole synchronization chain (RRC → AGC → Costas → Farrow/Gardner timing) closes timing out of context at 100 MHz on the xc7a100t-1 after place and route, with no failing endpoints (slack in the CSV). It uses 1,998 LUTs (3.2% of the device's 63,400), 2,659 flip-flops, 22 DSP48E1s and one RAMB18 (the Costas loop's sine table). The per-block rows are the same instances inside the chain, so their slack is the chain's. The RRC's flip-flops are its 57-sample delay lines for both rails. The first chain build met timing by only +0.525 ns, on the timing block's coefficient adders, 0.22 ns less than that block alone, because placement inside a larger design lengthened the routes. Splitting those adders over two stages gave +1.431 ns. The worst path is now the timing block's registered last Horner value through the output add and saturation (11 logic levels). Out-of-context results exclude I/O and clocking; the full receiver top will be more crowded.
