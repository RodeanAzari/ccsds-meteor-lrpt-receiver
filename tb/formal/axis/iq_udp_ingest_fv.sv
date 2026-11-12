`default_nettype none

// AXI4-Stream handshake check for iq_udp_ingest (tb/formal/axis.sby, generated layout): reset in the first cycle, every
// other input free; axis_props assumed on the inputs, asserted on the outputs. Parameters shrunk for formal: SAMPLES = 2, DEPTH = 8.
module iq_udp_ingest_fv (
    input wire logic clk_i,
    input wire logic rst_i,
    input wire logic [7:0] s_tdata_i,
    input wire logic s_tvalid_i,
    input wire logic s_tlast_i,
    input wire logic [0:0] s_tuser_i,
    input wire logic m_tready_i
);

    logic first_q = 1'b1;
    logic s_tready;
    logic [15:0] m_tdata;
    logic m_tvalid;
    logic [31:0] ok_cnt;
    logic [31:0] bad_cnt;
    logic [31:0] gap_cnt;
    logic [31:0] lost_cnt;
    logic [31:0] late_cnt;

    always_ff @(posedge clk_i) first_q <= 1'b0;
    always_comb if (first_q) assume (rst_i);

    iq_udp_ingest #(
        .SAMPLES (2),
        .DEPTH (8)
    ) u_dut (
        .clk_i (clk_i),
        .rst_i (rst_i),
        .s_tdata_i (s_tdata_i),
        .s_tvalid_i (s_tvalid_i),
        .s_tready_o (s_tready),
        .s_tlast_i (s_tlast_i),
        .s_tuser_i (s_tuser_i),
        .m_tdata_o (m_tdata),
        .m_tvalid_o (m_tvalid),
        .m_tready_i (m_tready_i),
        .ok_cnt_o (ok_cnt),
        .bad_cnt_o (bad_cnt),
        .gap_cnt_o (gap_cnt),
        .lost_cnt_o (lost_cnt),
        .late_cnt_o (late_cnt)
    );

    axis_props #(.W(8), .UW(1), .IS_INPUT(1'b1)) u_s_in (
        .clk_i (clk_i), .rst_i (rst_i), .tvalid (s_tvalid_i), .tready (s_tready), .tdata (s_tdata_i),
        .tlast (s_tlast_i), .tuser (s_tuser_i)
    );

    axis_props #(.W(16), .UW(1), .IS_INPUT(1'b0)) u_m_out (
        .clk_i (clk_i), .rst_i (rst_i), .tvalid (m_tvalid), .tready (m_tready_i), .tdata (m_tdata),
        .tlast (1'b0), .tuser (1'b0)
    );

endmodule

`default_nettype wire
