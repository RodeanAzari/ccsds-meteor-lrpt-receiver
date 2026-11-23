# Program the ILA build of arty_rx_eth_top and capture the Viterbi ACS path metrics during one replay (Phase D media).
#
#   scripts/vivado.sh -mode batch -source syn/ila_capture_acs.tcl -tclargs <bit> <ltx> <out.csv> <iface> <rec> <python>
#   make ila-capture-acs    (claim the board first: fpga-coord PROTOCOL §6)
#
# The ILA stores one entry per ACS step (storage qualified on the step enable, probe3; see impl_board.tcl) and
# triggers on the first step after arming. Arm, then replay the recording once (scripts/ila_viterbi.py replay: link,
# SET_NCO, gs-replay at 1x); the first ACS step comes once frame sync has locked.

lassign $argv bit ltx csv iface rec python
if {$python eq ""} { error "usage: -tclargs <bit> <ltx> <out.csv> <iface> <recording.cu8> <python>" }

open_hw_manager
connect_hw_server -allow_non_jtag
open_hw_target
set dev [lindex [get_hw_devices xc7a100t_0] 0]
set_property PROGRAM.FILE $bit $dev
set_property PROBES.FILE  $ltx $dev
set_property FULL_PROBES.FILE $ltx $dev
program_hw_devices $dev
refresh_hw_device $dev

set ila [lindex [get_hw_ilas -of_objects $dev] 0]
# By ILA port (impl_board.tcl order: probe0 path metrics, probe1 symbols, probe2 decisions, probe3 step enable).
set ce [get_hw_probes -of_objects $ila -filter {MAP =~ probe3*}]
if {[llength $ce] != 1} { error "ILA step-enable probe not found (rebuild with make board BOARD_TOP=arty_rx_eth_top ILA=1)" }

set_property CONTROL.DATA_DEPTH 1024 $ila
set_property CONTROL.TRIGGER_POSITION 0 $ila
set_property CONTROL.CAPTURE_MODE BASIC $ila
set_property CONTROL.TRIGGER_CONDITION AND $ila
set_property CONTROL.CAPTURE_CONDITION AND $ila
set_property TRIGGER_COMPARE_VALUE eq1'b1 $ce
set_property CAPTURE_COMPARE_VALUE eq1'b1 $ce

run_hw_ila $ila
puts "ILA armed; replaying $rec"
set root [file normalize [file join [file dirname [info script]] ..]]
cd $root  ;# scripts resolve build/ paths from the repo root
puts [exec env -u PYTHONHOME -u LD_LIBRARY_PATH PYTHONPATH=$root $python [file join $root scripts ila_viterbi.py] replay $iface $rec 2>@1]
wait_on_hw_ila -timeout 1 $ila
set data [upload_hw_ila_data $ila]
write_hw_ila_data -force -csv_file $csv $data
# Same capture in Vivado's format, for viewing offline: display_hw_ila_data [read_hw_ila_data <file>.ila]
write_hw_ila_data -force [file rootname $csv].ila $data
set f [open [file rootname $csv]_settings.txt w]
foreach p {CONTROL.DATA_DEPTH CONTROL.TRIGGER_POSITION CONTROL.CAPTURE_MODE CONTROL.TRIGGER_CONDITION
           CONTROL.CAPTURE_CONDITION} { puts $f "$p [get_property $p $ila]" }
# Probes 0-2 are data only (no compare values); only the step enable triggers and qualifies storage.
puts $f "probe $ce [get_property MAP $ce] trigger=[get_property TRIGGER_COMPARE_VALUE $ce]\
    capture=[get_property CAPTURE_COMPARE_VALUE $ce]"
puts $f "data probes: [llength [get_hw_probes -of_objects $ila]] hw_probes in all (Vivado splits a probe by net name)"
close $f
puts "ILA_CAPTURE $csv"
close_hw_target
