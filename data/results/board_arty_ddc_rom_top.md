# board_arty_ddc_rom_top

- **Commit:** `8f4076e7cbd4bc043182006192247922e7db47e9`
- **Command:** `make board`
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1, Vivado 2025.2
- **Input:** synthetic, no input data: board-level place and route (constr/arty_a7_100t.xdc) of arty_ddc_rom_top on xc7a100tcsg324-1. No real recording.

The Phase B bring-up design (BRAM ROM snippet, DDC, capture BRAM, UART) closes timing at 100 MHz with I/O placed on the Arty A7-100T. The first build missed by 0.155 ns on the DC-block path fed straight from the ROM's BRAM output; splitting the DC block into three stages fixed it with no change to the arithmetic. Block RAM dominates (64 Kword ROM + 16 Kword capture buffer); the DDC itself is unchanged from the out-of-context result. The ROM and capture buffer are bring-up scaffolding, replaced by the Ethernet path once eth-core-v0.1 is tagged.
