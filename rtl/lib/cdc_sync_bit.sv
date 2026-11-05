`default_nettype none

// Two-flop synchronizer for a single slow level (a button, a status bit) into clk_i (CLAUDE.md §5.1 CDC rule).
// Not for multi-bit values or pulses shorter than two destination clocks.
module cdc_sync_bit #(
    parameter int STAGES = 2
) (
    input  wire logic clk_i,
    input  wire logic d_i,  // asynchronous to clk_i
    output      logic q_o
);

    (* ASYNC_REG = "TRUE" *) logic [STAGES-1:0] sync_q;

    always_ff @(posedge clk_i) sync_q <= {sync_q[STAGES-2:0], d_i};

    assign q_o = sync_q[STAGES-1];

endmodule

`default_nettype wire
