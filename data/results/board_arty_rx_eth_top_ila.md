# board_arty_rx_eth_top_ila

- **Commit:** `d716e036ec2d7cb7c7a1ad4974c64dcf289de9c0 (with uncommitted changes)`
  The uncommitted change was `syn/impl_board.tcl`'s receiver-top ILA, committed unchanged in cc24881 (file last edited before the build started).
- **Command:** `make board BOARD_TOP=arty_rx_eth_top ILA=1`
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1, Vivado 2025.2
- **Input:** synthetic, no input data: board-level place and route (constr/arty_a7_100t.xdc) of arty_rx_eth_top_ila on xc7a100tcsg324-1. No real recording.

The debug build of the whole receiver (`make board BOARD_TOP=arty_rx_eth_top ILA=1`) is `arty_rx_eth_top` plus one ILA on the Viterbi ACS array, inserted by `syn/impl_board.tcl` after synthesis; the RTL is unchanged (CLAUDE.md §3.8). The ILA probes all 64 path metrics (576 bits), the step's two soft symbols (8), the decisions (64) and the path-metric registers' clock enable (1), and stores only steps, 1,024 deep. Probes 0–2 are data only: with a trigger comparator on every probe, the 576-bit comparator's 72-deep carry chain failed 100 MHz (WNS −0.612 ns, both failing paths inside the ILA). As built it closes at 100 MHz: WNS +0.421 ns, WHS +0.019 ns. The hold margin is thin but positive, as on the Phase B ILA build. Against the functional build (board_arty_rx_eth_top.csv) the ILA and debug hub cost 1,643 LUTs, 3,804 flip-flops and 18 RAMB36 + 1 RAMB18, the 1,024 × 649-bit sample buffer.
