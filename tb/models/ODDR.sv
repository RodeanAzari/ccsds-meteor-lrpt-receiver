// Lint and simulation stand-in for the Xilinx ODDR, OPPOSITE_EDGE with D1 = 1, D2 = 0 only (clock forwarding):
// the output follows C. Vivado uses its own.
/* verilator lint_off UNUSEDPARAM */
/* verilator lint_off UNUSEDSIGNAL */
module ODDR #(
    parameter string    DDR_CLK_EDGE = "OPPOSITE_EDGE",
    parameter bit       INIT         = 1'b0,
    parameter string    SRTYPE       = "SYNC"
) (
    input  wire C, CE, D1, D2, R, S,
    output wire Q
);
    assign Q = C & D1 & ~D2;
endmodule
/* verilator lint_on UNUSEDSIGNAL */
/* verilator lint_on UNUSEDPARAM */
