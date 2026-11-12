`default_nettype none

// AXI4-Stream handshake check for fec_viterbi (tb/formal/axis.sby, generated layout): reset in the first cycle, every
// other input free; axis_props assumed on the inputs, asserted on the outputs. Parameters shrunk for formal: ROWS = 16.
module fec_viterbi_fv (
    input wire logic clk_i,
    input wire logic rst_i,
    input wire logic [7:0] s_tdata_i,
    input wire logic s_tvalid_i,
    input wire logic m_tready_i,
    input wire logic [3:0] depth_i
);

    logic first_q = 1'b1;
    logic s_tready;
    logic [0:0] m_tdata;
    logic m_tvalid;

    always_ff @(posedge clk_i) first_q <= 1'b0;
    always_comb if (first_q) assume (rst_i);

    fec_viterbi #(
        .ROWS (16)
    ) u_dut (
        .clk_i (clk_i),
        .rst_i (rst_i),
        .s_tdata_i (s_tdata_i),
        .s_tvalid_i (s_tvalid_i),
        .s_tready_o (s_tready),
        .m_tdata_o (m_tdata),
        .m_tvalid_o (m_tvalid),
        .m_tready_i (m_tready_i),
        .depth_i (depth_i)
    );

    axis_props #(.W(8), .UW(1), .IS_INPUT(1'b1)) u_s_in (
        .clk_i (clk_i), .rst_i (rst_i), .tvalid (s_tvalid_i), .tready (s_tready), .tdata (s_tdata_i),
        .tlast (1'b0), .tuser (1'b0)
    );

    axis_props #(.W(1), .UW(1), .IS_INPUT(1'b0)) u_m_out (
        .clk_i (clk_i), .rst_i (rst_i), .tvalid (m_tvalid), .tready (m_tready_i), .tdata (m_tdata),
        .tlast (1'b0), .tuser (1'b0)
    );

endmodule

`default_nettype wire
