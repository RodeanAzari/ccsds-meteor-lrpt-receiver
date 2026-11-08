# board_arty_rx_eth_top

- **Commit:** `013d5e35b508ab358698d313480ed8a11dbc5c99 (with uncommitted changes)`
- **Command:** `make board BOARD_TOP=arty_rx_eth_top BOARD_GENERICS="FREQ_WORD=32'h25C11200"`
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1, Vivado 2025.2
- **Input:** synthetic, no input data: board-level place and route (constr/arty_a7_100t.xdc) of arty_rx_eth_top with FREQ_WORD=32'h25C11200 on xc7a100tcsg324-1. No real recording.

The whole receiver as a board design (`rtl/top/arty_rx_eth_top.sv`: fpga-eth-core RX/TX, ingest, DDC, `rx_chain` with fpga-rs-core, CADU and stats packets, `pkt_arb2`) places and routes on the Arty A7-100T at 100 MHz with timing met: WNS +0.580 ns, WHS +0.007 ns, no failing endpoints and no critical warnings. It uses 13,543 LUTs (21.4% of 63,400), 13,558 flip-flops, 29 DSP48E1 (12.1% of 240), 7 RAMB36 and 8 RAMB18: 161 LUTs below the rx_chain's own build (`synth_rx_chain.csv`, 11,247) plus the Ethernet DDC top (`board_arty_ddc_eth_top.csv`, 2,457), which this top replaces the capture and UART of. The worst hold path is inside the DDC (ingest output register → mixer input), met with 7 ps; the worst setup path is the chain's. This build carries the NCO word for the synthetic recording (`FREQ_WORD=32'h25C11200`, `scripts/board_rx.py freq-word`); another recording needs a rebuild with its own word until a control path exists. Bitstream used by `board_rx_eth.csv`.
