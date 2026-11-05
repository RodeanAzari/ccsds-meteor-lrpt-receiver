# Program the ILA build and capture every DDC output of one snippet replay (CLAUDE.md §3.8, Phase B media).
#
#   scripts/vivado.sh -mode batch -source syn/ila_capture.tcl -tclargs <bit> <ltx> <out.csv> <serial> <python>
#   make ila-capture    (claim the board first: fpga-coord PROTOCOL §6)
#
# The ILA stores only cycles where the DDC output handshakes (bb_tvalid && !full, see impl_board.tcl), triggering
# on the first. The snippet plays once after reset, and opening the serial port resets the design
# (observed; the mechanism is not established, docs/design.md), so: arm, open the port, wait for the full window.

lassign $argv bit ltx csv serial python
if {$csv eq ""} { error "usage: -tclargs <bit> <ltx> <out.csv> <serial> <python>" }

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
puts "ILA probes: [get_hw_probes -of_objects $ila]"
# By ILA port (impl_board.tcl order: probe0 bb_tdata, probe1 bb_tvalid, probe2 full, probe3 rom_done); the
# probe names are whatever synthesis called the nets.
set valid [get_hw_probes -of_objects $ila -filter {MAP =~ probe1*}]
set full  [get_hw_probes -of_objects $ila -filter {MAP =~ probe2*}]
puts "ILA valid=$valid full=$full" 
if {[llength $valid] != 1 || [llength $full] != 1} { error "ILA probes not found (rebuild with make board ILA=1)" }

set_property CONTROL.DATA_DEPTH 16384 $ila
set_property CONTROL.TRIGGER_POSITION 0 $ila
set_property CONTROL.CAPTURE_MODE BASIC $ila
set_property CONTROL.TRIGGER_CONDITION AND $ila
set_property CONTROL.CAPTURE_CONDITION AND $ila
foreach p [list $valid $full] v {eq1'b1 eq1'b0} {
    set_property TRIGGER_COMPARE_VALUE $v $p
    set_property CAPTURE_COMPARE_VALUE $v $p
}

run_hw_ila $ila
puts "ILA armed; resetting the design through the serial port"
exec env -u PYTHONHOME -u PYTHONPATH $python -c "import serial, time; s = serial.Serial('$serial'); time.sleep(0.3); s.close()"
wait_on_hw_ila -timeout 1 $ila
set data [upload_hw_ila_data $ila]
write_hw_ila_data -force -csv_file $csv $data
# Same capture in Vivado's format, for viewing offline: display_hw_ila_data [read_hw_ila_data <file>.ila]
write_hw_ila_data -force [file rootname $csv].ila $data
# The trigger/capture settings actually used, as evidence next to the data.
set f [open [file rootname $csv]_settings.txt w]
foreach p {CONTROL.DATA_DEPTH CONTROL.TRIGGER_POSITION CONTROL.CAPTURE_MODE CONTROL.TRIGGER_CONDITION
           CONTROL.CAPTURE_CONDITION} { puts $f "$p [get_property $p $ila]" }
foreach p [get_hw_probes -of_objects $ila] {
    puts $f "probe $p [get_property MAP $p] trigger=[get_property TRIGGER_COMPARE_VALUE $p]\
        capture=[get_property CAPTURE_COMPARE_VALUE $p]"
}
close $f
puts "ILA_CAPTURE $csv"
close_hw_target
