`default_nettype none

// Formal harness for fec_acs_array (tb/formal/fec_acs_array.sby): reset in the first cycle, s_tdata free, so the ACS
// sees every branch-metric sequence. The properties are the RTL's own SVA. With ALWAYS_STEP (task step) the array
// takes a step every clock: k-induction cannot see through a stall (the metrics hold, so k cycles can be one state),
// and task hold proves with free handshakes that a stall changes no metric.
module fec_acs_array_fv #(
    parameter int SOFT_BITS = 4,  // ADR 0005; narrower widths with chparam
    parameter int PM_BITS   = 9   // viterbi_fixed.path_metric_bits(SOFT_BITS)
) (
    input wire logic                   clk_i,
    input wire logic                   rst_i,
    input wire logic [2*SOFT_BITS-1:0] s_tdata_i,
    input wire logic                   s_tvalid_i,
    input wire logic                   m_tready_i
);

    logic first_q = 1'b1;

    always_ff @(posedge clk_i) first_q <= 1'b0;
    always_comb if (first_q) assume (rst_i);
`ifdef ALWAYS_STEP
    always_comb assume (s_tvalid_i && m_tready_i);
`endif

    /* verilator lint_off PINCONNECTEMPTY */
    fec_acs_array #(
        .SOFT_BITS (SOFT_BITS),
        .PM_BITS   (PM_BITS)
    ) u_dut (
        .clk_i      (clk_i),
        .rst_i      (rst_i),
        .s_tdata_i  (s_tdata_i),
        .s_tvalid_i (s_tvalid_i),
        .s_tready_o (),
        .m_tdata_o  (),
        .m_tvalid_o (),
        .m_tready_i (m_tready_i)
    );
    /* verilator lint_on PINCONNECTEMPTY */

endmodule

`default_nettype wire
