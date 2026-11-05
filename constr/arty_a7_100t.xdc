## Arty A7-100T pins used by the Phase B bring-up top (rtl/top/arty_ddc_rom_top.sv).
## Pin numbers from Digilent's Arty-A7-100-Master.xdc.

set_property -dict { PACKAGE_PIN E3  IOSTANDARD LVCMOS33 } [get_ports clk100_i]
create_clock -name clk100 -period 10.000 [get_ports clk100_i]

set_property -dict { PACKAGE_PIN C2  IOSTANDARD LVCMOS33 } [get_ports ck_rst_n_i]
set_property -dict { PACKAGE_PIN D9  IOSTANDARD LVCMOS33 } [get_ports btn0_i]
set_property -dict { PACKAGE_PIN D10 IOSTANDARD LVCMOS33 } [get_ports uart_txd_o]
set_property -dict { PACKAGE_PIN H5  IOSTANDARD LVCMOS33 } [get_ports {led_o[0]}]
set_property -dict { PACKAGE_PIN J5  IOSTANDARD LVCMOS33 } [get_ports {led_o[1]}]
set_property -dict { PACKAGE_PIN T9  IOSTANDARD LVCMOS33 } [get_ports {led_o[2]}]
set_property -dict { PACKAGE_PIN T10 IOSTANDARD LVCMOS33 } [get_ports {led_o[3]}]

## Asynchronous inputs go through reset_sync / cdc_sync_bit (docs/design.md, CDC list); outputs are slow
## (115,200 baud UART, LEDs), so no I/O timing applies.
set_false_path -from [get_ports {ck_rst_n_i btn0_i}]
set_false_path -to   [get_ports {uart_txd_o led_o[*]}]

## Bank voltage for configuration (Arty: 3.3 V on bank 0)
set_property CFGBVS VCCO        [current_design]
set_property CONFIG_VOLTAGE 3.3 [current_design]
