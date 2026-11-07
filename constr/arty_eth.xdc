## Ethernet-fed tops (rtl/top/arty_ddc_eth_top.sv): MII pins, PHY clocks and the crossings to rx_clk and tx_clk.
## Read after arty_a7_100t.xdc (clock, button, UART, LEDs), and with fpga-eth-core's constr/async_fifo.xdc scoped
## to async_fifo (syn/impl_board.tcl). Pins from Digilent's Arty-A7-100-Master.xdc (eth_* section), as used by
## fpga-eth-core's constr/arty_a7_100_pins.xdc at eth-core-v0.2; timing values from its udp_echo_timing.xdc.

set_property -dict { PACKAGE_PIN G18 IOSTANDARD LVCMOS33 } [get_ports eth_ref_clk_o]
set_property -dict { PACKAGE_PIN C16 IOSTANDARD LVCMOS33 } [get_ports eth_rstn_o]
set_property -dict { PACKAGE_PIN F16 IOSTANDARD LVCMOS33 } [get_ports eth_mdc_o]
set_property -dict { PACKAGE_PIN F15 IOSTANDARD LVCMOS33 } [get_ports eth_rx_clk_i]
set_property -dict { PACKAGE_PIN G16 IOSTANDARD LVCMOS33 } [get_ports eth_rx_dv_i]
set_property -dict { PACKAGE_PIN D18 IOSTANDARD LVCMOS33 } [get_ports {eth_rxd_i[0]}]
set_property -dict { PACKAGE_PIN E17 IOSTANDARD LVCMOS33 } [get_ports {eth_rxd_i[1]}]
set_property -dict { PACKAGE_PIN E18 IOSTANDARD LVCMOS33 } [get_ports {eth_rxd_i[2]}]
set_property -dict { PACKAGE_PIN G17 IOSTANDARD LVCMOS33 } [get_ports {eth_rxd_i[3]}]
set_property -dict { PACKAGE_PIN C17 IOSTANDARD LVCMOS33 } [get_ports eth_rxerr_i]
set_property -dict { PACKAGE_PIN H16 IOSTANDARD LVCMOS33 } [get_ports eth_tx_clk_i]
set_property -dict { PACKAGE_PIN H15 IOSTANDARD LVCMOS33 } [get_ports eth_tx_en_o]
set_property -dict { PACKAGE_PIN H14 IOSTANDARD LVCMOS33 } [get_ports {eth_txd_o[0]}]
set_property -dict { PACKAGE_PIN J14 IOSTANDARD LVCMOS33 } [get_ports {eth_txd_o[1]}]
set_property -dict { PACKAGE_PIN J13 IOSTANDARD LVCMOS33 } [get_ports {eth_txd_o[2]}]
set_property -dict { PACKAGE_PIN H17 IOSTANDARD LVCMOS33 } [get_ports {eth_txd_o[3]}]

## PHY receive clock, 25 MHz at 100 Mb/s (802.3 clause 22). The 100 MHz core clock comes from the MMCM and is
## derived automatically from clk100.
create_clock -name eth_rx_clk -period 40.000 [get_ports eth_rx_clk_i]
## PHY transmit clock, 25 MHz at 100 Mb/s, an input from the PHY (802.3 clause 22.2.2.1).
create_clock -name eth_tx_clk -period 40.000 [get_ports eth_tx_clk_i]
## The 25 MHz PHY reference leaves through an ODDR (rtl/lib/xilinx/clk_gen_eth.sv).
create_generated_clock -name eth_ref_clk_out -divide_by 1 -source [get_pins u_clk/u_oddr_ref/C] \
    [get_ports eth_ref_clk_o]

## MII receive inputs. TI DP83848 datasheet SNLS250E, T2.5.2: RX_CLK to RXD/RX_DV/RX_ER 10 ns min, 30 ns max at
## 100 Mb/s, sampled on the next rising edge. Board trace delays neglected (short, matched).
set mii_in [get_ports {eth_rxd_i[*] eth_rx_dv_i eth_rxerr_i}]
set_input_delay -clock eth_rx_clk -max 30.000 $mii_in
set_input_delay -clock eth_rx_clk -min 10.000 $mii_in
set_property IOB TRUE [get_cells -hier -filter {NAME =~ *u_mii_rx/rxd_q_reg*}]
set_property IOB TRUE [get_cells -hier -filter {NAME =~ *u_mii_rx/dv_q_reg}]
set_property IOB TRUE [get_cells -hier -filter {NAME =~ *u_mii_rx/er_q_reg}]

## MII transmit outputs. DP83848 SNLS250E, T2.4.2: TXD/TX_EN setup to TX_CLK 10 ns min; T2.4.3 hold 0 ns.
## mii_tx launches from IOB flops on TX_CLK's rising edge; the PHY captures on the next one.
set mii_out [get_ports {eth_txd_o[*] eth_tx_en_o}]
set_output_delay -clock eth_tx_clk -max 10.000 $mii_out
set_output_delay -clock eth_tx_clk -min 0.000 $mii_out
set_property IOB TRUE [get_cells -hier -filter {NAME =~ *u_mii_tx/mii_txd_o_reg*}]
set_property IOB TRUE [get_cells -hier -filter {NAME =~ *u_mii_tx/mii_tx_en_o_reg}]

## Crossings (docs/design.md CDC list):
## 1. async FIFO Gray pointers inside eth_rx: fpga-eth-core's async_fifo.xdc, scoped.
## 2. MAC reset request (core) -> u_rst_mii (rx_clk): asynchronous preset of the synchronizer, released through
##    its flop chain. Recovery/removal across the unrelated clocks is not meaningful.
set_false_path -to [get_pins -hier -filter {NAME =~ *u_rst_mii/sync_q_reg*/PRE}]
set_false_path -to [get_pins -hier -filter {NAME =~ *u_rst_mii_tx/sync_q_reg*/PRE}]
## 3. async FIFO inside eth_tx (core -> tx_clk): eth-core's async_fifo.xdc, scoped.
## 4. eth_tx underrun toggle (tx_clk -> core): a level into eth-core's ASYNC_REG chain, changing at most once per
##    frame; only its skew is bounded (fpga-eth-core udp_echo_timing.xdc).
set_max_delay -datapath_only -from [get_cells -hier -filter {NAME =~ *u_eth_tx/underrun_tgl_q_reg}] \
    -to [get_cells -hier -filter {NAME =~ *u_eth_tx/underrun_sync_q_reg[0]}] 8.000

## Static outputs: PHY reset and MDC levels.
set_false_path -to [get_ports {eth_rstn_o eth_mdc_o}]
