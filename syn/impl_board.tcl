# Board build: synth -> place -> route -> bitstream for a top on the Arty A7-100T (CLAUDE.md §6, batch only).
#
#   scripts/vivado.sh -mode batch -source syn/impl_board.tcl -tclargs <top> <rom.mem>
#   make board          (top arty_ddc_rom_top; generates the ROM snippet first)
#
# Reports go to docs/reports/board/<top>/; the bitstream to build/board/<top>.bit.
# A build with negative slack is reported as failed (CLAUDE.md §6: timing closure is required).

set pinned_version 2025.2  ;# docs/toolchain.md
if {[version -short] ne $pinned_version} {
    puts "WARNING: Vivado [version -short] is not the pinned $pinned_version (docs/toolchain.md)"
}

set top  [lindex $argv 0]
set rom  [file normalize [lindex $argv 1]]
set part xc7a100tcsg324-1
if {$top eq "" || ![file exists $rom]} { error "usage: -tclargs <top> <rom.mem>" }

set root [file normalize [file join [file dirname [info script]] ..]]
set out  [file join $root docs reports board $top]
set bdir [file join $root build board]
file mkdir $out $bdir

set srcs [lsort [glob -nocomplain [file join $root rtl * *.sv]]]
set srcs [lsearch -all -inline -not -glob $srcs */rtl/eth/*]
read_verilog -sv $srcs
foreach f [glob -nocomplain [file join $root rtl * *.mem]] { read_mem $f }
read_mem $rom  ;# the ROM_FILE default "iq_rom.mem" resolves to this file
read_xdc [file join $root constr arty_a7_100t.xdc]

synth_design -top $top -part $part -flatten_hierarchy rebuilt
opt_design
place_design
route_design

report_timing_summary -max_paths 10 -file [file join $out timing_summary.rpt]
report_utilization -file [file join $out utilization.rpt]
report_utilization -hierarchical -file [file join $out utilization_hier.rpt]
report_drc -file [file join $out drc.rpt]
report_power -file [file join $out power.rpt]

set wns [get_property SLACK [get_timing_paths -max_paths 1 -setup]]
set whs [get_property SLACK [get_timing_paths -max_paths 1 -hold]]
set f [open [file join $out summary.txt] w]
puts $f "top $top"
puts $f "part $part"
puts $f "vivado [version -short]"
puts $f "clk_mhz 100"
puts $f "wns_ns $wns"
close $f
puts "BOARD $top: WNS $wns ns, WHS $whs ns"
if {$wns < 0 || $whs < 0} { error "timing not met: no bitstream written" }

write_bitstream -force [file join $bdir $top.bit]
