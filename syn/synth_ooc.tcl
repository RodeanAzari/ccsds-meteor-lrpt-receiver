# Out-of-context synthesis, placement and routing of one RTL block (CLAUDE.md §6: batch Tcl, no GUI steps).
#
#   scripts/vivado.sh -mode batch -source syn/synth_ooc.tcl -tclargs <top> [clk_mhz] [part]
#   make synth-ooc TOP=ddc_top
#
# Out of context: the block's ports are internal streams, not pins, so no I/O buffers or pin constraints.
# It runs to route_design because post-synthesis timing is an estimate of routing delay; post-route is measured.
# Reports go to docs/reports/ooc/<top>/; analysis/synth_report.py turns them into data/results/synth_<top>.csv.

set pinned_version 2025.2  ;# docs/toolchain.md
if {[version -short] ne $pinned_version} {
    puts "WARNING: Vivado [version -short] is not the pinned $pinned_version (docs/toolchain.md)"
}

set top     [lindex $argv 0]
set clk_mhz [expr {[llength $argv] > 1 ? [lindex $argv 1] : 100}]
set part    [expr {[llength $argv] > 2 ? [lindex $argv 2] : "xc7a100tcsg324-1"}]
if {$top eq ""} { error "usage: -tclargs <top> \[clk_mhz\] \[part\]" }

set root [file normalize [file join [file dirname [info script]] ..]]
set out  [file join $root docs reports ooc $top]
file mkdir $out

# Every RTL source outside the Ethernet submodule; synth_design keeps only what $top instantiates.
set srcs [lsort [glob -nocomplain [file join $root rtl * *.sv]]]
set srcs [lsearch -all -inline -not -glob $srcs */rtl/eth/*]
read_verilog -sv $srcs
# ROM/coefficient files for $readmemh, written by scripts/gen_rtl_tables.py
foreach f [glob -nocomplain [file join $root rtl * *.mem]] { read_mem $f }

synth_design -top $top -part $part -mode out_of_context -flatten_hierarchy rebuilt
create_clock -name clk -period [expr {1000.0 / $clk_mhz}] [get_ports clk_i]
report_utilization -file [file join $out synth_utilization.rpt]

opt_design
place_design
route_design

report_timing_summary -max_paths 10 -file [file join $out timing_summary.rpt]
report_utilization -file [file join $out utilization.rpt]
report_utilization -hierarchical -file [file join $out utilization_hier.rpt]
report_drc -file [file join $out drc.rpt]

set wns [get_property SLACK [get_timing_paths -max_paths 1 -setup]]
set f [open [file join $out summary.txt] w]
puts $f "top $top"
puts $f "part $part"
puts $f "vivado [version -short]"
puts $f "clk_mhz $clk_mhz"
puts $f "wns_ns $wns"
close $f
puts "OOC $top @ $clk_mhz MHz: WNS $wns ns"
