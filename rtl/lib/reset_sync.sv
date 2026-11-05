`default_nettype none

// Reset synchronizer: asynchronous assert, synchronous deassert, active-high out (CLAUDE.md §5.1: one per clock
// domain). The input may come straight from a pin or button.
module reset_sync #(
    parameter int STAGES = 3  // > 2 flops for metastability settling on deassert
) (
    input  wire logic clk_i,
    input  wire logic rst_async_i,  // active-high, asynchronous
    output      logic rst_o         // active-high, synchronous to clk_i
);

    (* ASYNC_REG = "TRUE" *) logic [STAGES-1:0] sync_q;

    always_ff @(posedge clk_i or posedge rst_async_i) begin
        if (rst_async_i) sync_q <= '1;
        else             sync_q <= {sync_q[STAGES-2:0], 1'b0};
    end

    assign rst_o = sync_q[STAGES-1];

endmodule

`default_nettype wire
