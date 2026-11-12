`default_nettype none

// AXI4-Stream handshake check for stats_packet (tb/formal/axis.sby, generated layout): reset in the first cycle, every
// other input free; axis_props assumed on the inputs, asserted on the outputs. Parameters shrunk for formal: N_FIELDS = 2, PERIOD = 64.
module stats_packet_fv (
    input wire logic clk_i,
    input wire logic rst_i,
    input wire logic m_tready_i,
    input wire logic enable_i,
    input wire logic [63:0] fields_i
);

    logic first_q = 1'b1;
    logic [7:0] m_tdata;
    logic m_tvalid;
    logic m_tlast;

    always_ff @(posedge clk_i) first_q <= 1'b0;
    always_comb if (first_q) assume (rst_i);

    stats_packet #(
        .N_FIELDS (2),
        .PERIOD (64)
    ) u_dut (
        .clk_i (clk_i),
        .rst_i (rst_i),
        .m_tdata_o (m_tdata),
        .m_tvalid_o (m_tvalid),
        .m_tready_i (m_tready_i),
        .m_tlast_o (m_tlast),
        .enable_i (enable_i),
        .fields_i (fields_i)
    );

    axis_props #(.W(8), .UW(1), .IS_INPUT(1'b0)) u_m_out (
        .clk_i (clk_i), .rst_i (rst_i), .tvalid (m_tvalid), .tready (m_tready_i), .tdata (m_tdata),
        .tlast (m_tlast), .tuser (1'b0)
    );

endmodule

`default_nettype wire
