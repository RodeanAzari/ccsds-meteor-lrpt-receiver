`default_nettype none

// AXI4-Stream handshake rules on one interface (buildplan §8.3; CLAUDE.md §3.1), for SymbiYosys. On a block's input
// (IS_INPUT = 1) they are assumptions about the upstream; on its output they are assertions about the block:
//   - the cycle after a reset cycle, tvalid is low (AXI4-Stream: tvalid low during reset; our resets are synchronous,
//     so a registered tvalid shows it one cycle later);
//   - once tvalid is high and tready low, the next cycle (reset aside) tvalid stays high and tdata, tlast, tuser stay
//     unchanged: a beat, once offered, is neither withdrawn nor changed before it is taken.
// tlast and tuser are optional (tie them to 0 and leave LW/UW at 1 when the interface has none).
module axis_props #(
    parameter int W        = 8,
    parameter int UW       = 1,
    parameter bit IS_INPUT = 1'b0
) (
    input wire logic          clk_i,
    input wire logic          rst_i,
    input wire logic          tvalid,
    input wire logic          tready,
    input wire logic [W-1:0]  tdata,
    input wire logic          tlast,
    input wire logic [UW-1:0] tuser
);

    logic          past_q = 1'b0;  // $past is valid from the second cycle
    logic          rst_q, stall_q;
    logic [W-1:0]  data_q;
    logic          last_q;
    logic [UW-1:0] user_q;
    logic          ok_reset, ok_stall;

    always_ff @(posedge clk_i) begin
        past_q  <= 1'b1;
        rst_q   <= rst_i;
        stall_q <= tvalid && !tready;
        data_q  <= tdata;
        last_q  <= tlast;
        user_q  <= tuser;
    end

    always_comb begin
        ok_reset = !(past_q && rst_q) || !tvalid;
        ok_stall = !(past_q && !rst_q && !rst_i && stall_q)
                   || (tvalid && tdata == data_q && tlast == last_q && tuser == user_q);
    end

    if (IS_INPUT) begin : g_assume
        always_comb begin
            assume (ok_reset);
            assume (ok_stall);
        end
    end else begin : g_assert
        always_comb begin
            a_reset: assert (ok_reset);
            a_stall: assert (ok_stall);
        end
    end

endmodule

`default_nettype wire
