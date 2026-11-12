`default_nettype none

// AXI4-Stream handshake check for pkt_arb2 (tb/formal/axis.sby, generated layout): reset in the first cycle, every
// other input free; axis_props assumed on the inputs, asserted on the outputs.
module pkt_arb2_fv (
    input wire logic clk_i,
    input wire logic rst_i,
    input wire logic [7:0] s0_tdata_i,
    input wire logic s0_tvalid_i,
    input wire logic s0_tlast_i,
    input wire logic [7:0] s1_tdata_i,
    input wire logic s1_tvalid_i,
    input wire logic s1_tlast_i,
    input wire logic m_tready_i
);

    logic first_q = 1'b1;
    logic s0_tready;
    logic s1_tready;
    logic [7:0] m_tdata;
    logic m_tvalid;
    logic m_tlast;

    always_ff @(posedge clk_i) first_q <= 1'b0;
    always_comb if (first_q) assume (rst_i);

    pkt_arb2 u_dut (
        .clk_i (clk_i),
        .rst_i (rst_i),
        .s0_tdata_i (s0_tdata_i),
        .s0_tvalid_i (s0_tvalid_i),
        .s0_tready_o (s0_tready),
        .s0_tlast_i (s0_tlast_i),
        .s1_tdata_i (s1_tdata_i),
        .s1_tvalid_i (s1_tvalid_i),
        .s1_tready_o (s1_tready),
        .s1_tlast_i (s1_tlast_i),
        .m_tdata_o (m_tdata),
        .m_tvalid_o (m_tvalid),
        .m_tready_i (m_tready_i),
        .m_tlast_o (m_tlast)
    );

    axis_props #(.W(8), .UW(1), .IS_INPUT(1'b1)) u_s0_in (
        .clk_i (clk_i), .rst_i (rst_i), .tvalid (s0_tvalid_i), .tready (s0_tready), .tdata (s0_tdata_i),
        .tlast (s0_tlast_i), .tuser (1'b0)
    );

    axis_props #(.W(8), .UW(1), .IS_INPUT(1'b1)) u_s1_in (
        .clk_i (clk_i), .rst_i (rst_i), .tvalid (s1_tvalid_i), .tready (s1_tready), .tdata (s1_tdata_i),
        .tlast (s1_tlast_i), .tuser (1'b0)
    );

    axis_props #(.W(8), .UW(1), .IS_INPUT(1'b0)) u_m_out (
        .clk_i (clk_i), .rst_i (rst_i), .tvalid (m_tvalid), .tready (m_tready_i), .tdata (m_tdata),
        .tlast (m_tlast), .tuser (1'b0)
    );

endmodule

`default_nettype wire
