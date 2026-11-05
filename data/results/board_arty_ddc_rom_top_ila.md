# board_arty_ddc_rom_top_ila

- **Commit:** `40f4d4feac92fc6c91ecabbca3884f574d926df1 (with uncommitted changes)`
- **Command:** `make board`
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1, Vivado 2025.2
- **Input:** synthetic, no input data: board-level place and route (constr/arty_a7_100t.xdc) of arty_ddc_rom_top_ila on xc7a100tcsg324-1. No real recording.

The debug build (`make board ILA=1`) is the Phase B bring-up design plus one ILA, inserted by `syn/impl_board.tcl` after synthesis. The RTL is unchanged, and the functional build doesn't depend on it (CLAUDE.md §3.8). The ILA probes the DDC output data (32 bits), its valid, and the capture buffer's full flag (whose inverse is the tready), and stores only handshake cycles, 16,384 deep. It still closes at 100 MHz: WNS +1.750 ns, WHS +0.024 ns. The hold margin is small but positive. Compared with the functional build, the ILA and debug hub cost 1,449 LUTs, 2,461 flip-flops and 16 RAMB36, the 16,384 × 35-bit sample buffer.
