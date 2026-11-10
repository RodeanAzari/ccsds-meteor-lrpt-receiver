# Board build: synth -> place -> route -> bitstream for a top on the Arty A7-100T (CLAUDE.md §6, batch only).
#
#   scripts/vivado.sh -mode batch -source syn/impl_board.tcl -tclargs <top> <rom.mem | none> [ila]
#   make board          (top arty_ddc_rom_top; generates the ROM snippet first)
#   make board BOARD_TOP=arty_ddc_eth_top   (Ethernet-fed; no ROM. Adds fpga-eth-core's rtl/ at its tag, the MII
#                        constraints constr/arty_eth.xdc and eth-core's async_fifo.xdc scoped to async_fifo)
#   make board BOARD_TOP=arty_rx_eth_top   (the whole receiver; the host sets the NCO word per replay, ADR 0014)
#   make board ILA=1    (same, plus an ILA on the DDC output, inserted here after synthesis; the RTL is unchanged.
#                        Outputs <top>_ila.bit / .ltx and reports under docs/reports/board/<top>_ila/)
#
# Reports go to docs/reports/board/<top>/; the bitstream to build/board/<top>.bit.
# A build with negative slack is reported as failed (CLAUDE.md §6: timing closure is required).

set pinned_version 2025.2  ;# docs/toolchain.md
if {[version -short] ne $pinned_version} {
    puts "WARNING: Vivado [version -short] is not the pinned $pinned_version (docs/toolchain.md)"
}

set top  [lindex $argv 0]
set rom  [lindex $argv 1]
set ila  [expr {[lindex $argv 2] eq "ila"}]
set name [expr {$ila ? "${top}_ila" : $top}]
# Optional environment BOARD_SUFFIX: a variant of the same top (e.g. _prers for RS_WRITEBACK=0) gets its own
# bitstream and reports
if {[info exists ::env(BOARD_SUFFIX)]} { append name $::env(BOARD_SUFFIX) }
set part xc7a100tcsg324-1
if {$top eq "" || ($rom ne "none" && ![file exists $rom])} { error "usage: -tclargs <top> <rom.mem | none> \[ila\]" }
set eth  [string match *_eth_* $top]

set root [file normalize [file join [file dirname [info script]] ..]]
set out  [file join $root docs reports board $name]
set bdir [file join $root build board]
file mkdir $out $bdir

set srcs [lsort [concat [glob -nocomplain [file join $root rtl * *.sv]] \
    [glob -nocomplain [file join $root rtl lib xilinx *.sv]]]]
set srcs [lsearch -all -inline -not -glob $srcs */rtl/eth/*]
if {$eth} { lappend srcs {*}[lsort [glob [file join $root rtl eth rtl *.sv]]] }  ;# fpga-eth-core at its tag
lappend srcs {*}[lsort [glob [file join $root rtl rs rtl *.sv]]]                  ;# fpga-rs-core at its tag
# Packages (rx_config_pkg, rs_gf_pkg) before the files that import them
set srcs [concat [lsearch -all -inline -glob $srcs *_pkg.sv] [lsearch -all -inline -not -glob $srcs *_pkg.sv]]
read_verilog -sv $srcs
foreach f [glob -nocomplain [file join $root rtl * *.mem]] { read_mem $f }
if {$rom ne "none"} { read_mem [file normalize $rom] }  ;# the ROM_FILE default "iq_rom.mem" resolves to this file
read_xdc [file join $root constr arty_a7_100t.xdc]
if {$eth} {
    read_xdc [file join $root constr arty_eth.xdc]
    read_xdc -ref async_fifo [file join $root rtl eth constr async_fifo.xdc]
}

# Optional environment BOARD_GENERICS: space-separated NAME=VALUE top parameter overrides (e.g. RS_WRITEBACK=0 for
# the pre-RS BER build), recorded in the build's summary.
set generics {}
if {[info exists ::env(BOARD_GENERICS)]} {
    foreach g $::env(BOARD_GENERICS) { lappend generics -generic $g }
}
synth_design -top $top -part $part -flatten_hierarchy rebuilt {*}$generics

# Debug build only (CLAUDE.md §3.8): ILA on the DDC output handshake. Storage qualification keeps only beats
# where the DDC output handshakes, so 16,384 entries hold every output of the 65,536-sample snippet.
if {$ila} {
    set clk [get_nets -of_objects [get_pins -of_objects [get_cells -hier -filter {REF_NAME == BUFG}] \
        -filter {DIRECTION == OUT}]]
    create_debug_core u_ila ila
    set_property C_DATA_DEPTH 16384 [get_debug_cores u_ila]
    set_property C_EN_STRG_QUAL true [get_debug_cores u_ila]
    set_property ALL_PROBE_SAME_MU true [get_debug_cores u_ila]
    set_property ALL_PROBE_SAME_MU_CNT 2 [get_debug_cores u_ila]
    set_property C_INPUT_PIPE_STAGES 1 [get_debug_cores u_ila]
    set_property port_width 1 [get_debug_ports u_ila/clk]
    connect_debug_port u_ila/clk $clk
    # Probes, by post-synthesis net name (checked; a rename fails the build). capture_dump's s_tready_o is
    # exactly !full_o, and full_o / rom_done drive LD6 / LD5, so the handshake is bb_tvalid && !full.
    set probes {bb_tdata 32 bb_tvalid 1 led_o_OBUF[2] 1 led_o_OBUF[1] 1}
    set i 0
    foreach {net width} $probes {
        if {$i > 0} { create_debug_port u_ila probe }
        set nets {}
        for {set b 0} {$b < $width} {incr b} {   ;# probe bit b = bus bit b, LSB first
            lappend nets [get_nets -quiet [expr {$width > 1 ? "${net}\[$b\]" : $net}]]
        }
        if {[llength [join $nets]] != $width} { error "ILA: net $net not found after synthesis" }
        set_property port_width $width [get_debug_ports u_ila/probe$i]
        connect_debug_port u_ila/probe$i [join $nets]
        incr i
    }
}
opt_design
place_design
route_design

report_timing_summary -max_paths 10 -file [file join $out timing_summary.rpt]
report_utilization -file [file join $out utilization.rpt]
report_utilization -hierarchical -file [file join $out utilization_hier.rpt]
report_drc -file [file join $out drc.rpt]
report_power -file [file join $out power.rpt]
report_clock_interaction -delay_type min_max -file [file join $out clock_interaction.rpt]

set wns [get_property SLACK [get_timing_paths -max_paths 1 -setup]]
set whs [get_property SLACK [get_timing_paths -max_paths 1 -hold]]
set f [open [file join $out summary.txt] w]
puts $f "top $name"
puts $f "part $part"
puts $f "vivado [version -short]"
puts $f "clk_mhz 100"
puts $f "wns_ns $wns"
if {[llength $generics]} { puts $f "generics $::env(BOARD_GENERICS)" }
if {[info exists ::env(BOARD_SUFFIX)] && $::env(BOARD_SUFFIX) ne ""} { puts $f "suffix $::env(BOARD_SUFFIX)" }
close $f
puts "BOARD $name: WNS $wns ns, WHS $whs ns"
if {$wns < 0 || $whs < 0} { error "timing not met: no bitstream written" }

write_bitstream -force [file join $bdir $name.bit]
if {$ila} { write_debug_probes -force [file join $bdir $name.ltx] }
