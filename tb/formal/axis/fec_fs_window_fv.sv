`default_nettype none

// AXI4-Stream handshake check for fec_fs_window (tb/formal/axis.sby, generated layout): reset in the first cycle, every
// other input free; axis_props assumed on the inputs, asserted on the outputs. Parameters shrunk for formal: FRAME = 16, PRE = 4, POST = 4, DEPTH = 64, POS_BITS = 8.
module fec_fs_window_fv (
    input wire logic clk_i,
    input wire logic rst_i,
    input wire logic [3:0] s_tdata_i,
    input wire logic s_tvalid_i,
    input wire logic m_tready_i,
    input wire logic d_valid_i [2],
    input wire logic [7:0] d_first_i [2],
    input wire logic [1:0] d_hyp_i [2],
    input wire logic d_fly_i [2]
);

    logic first_q = 1'b1;
    logic s_tready;
    logic [7:0] m_tdata;
    logic m_tvalid;
    logic m_tlast;
    logic [2:0] m_tuser;

    always_ff @(posedge clk_i) first_q <= 1'b0;
    always_comb if (first_q) assume (rst_i);

    fec_fs_window #(
        .FRAME (16),
        .PRE (4),
        .POST (4),
        .DEPTH (64),
        .POS_BITS (8)
    ) u_dut (
        .clk_i (clk_i),
        .rst_i (rst_i),
        .s_tdata_i (s_tdata_i),
        .s_tvalid_i (s_tvalid_i),
        .s_tready_o (s_tready),
        .m_tdata_o (m_tdata),
        .m_tvalid_o (m_tvalid),
        .m_tready_i (m_tready_i),
        .m_tlast_o (m_tlast),
        .m_tuser_o (m_tuser),
        .d_valid_i (d_valid_i),
        .d_first_i (d_first_i),
        .d_hyp_i (d_hyp_i),
        .d_fly_i (d_fly_i)
    );

    axis_props #(.W(4), .UW(1), .IS_INPUT(1'b1)) u_s_in (
        .clk_i (clk_i), .rst_i (rst_i), .tvalid (s_tvalid_i), .tready (s_tready), .tdata (s_tdata_i),
        .tlast (1'b0), .tuser (1'b0)
    );

    axis_props #(.W(8), .UW(3), .IS_INPUT(1'b0)) u_m_out (
        .clk_i (clk_i), .rst_i (rst_i), .tvalid (m_tvalid), .tready (m_tready_i), .tdata (m_tdata),
        .tlast (m_tlast), .tuser (m_tuser)
    );

endmodule

`default_nettype wire
