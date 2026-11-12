`default_nettype none

// AXI4-Stream handshake check for fec_frame_extract (tb/formal/axis.sby, generated layout): reset in the first cycle, every
// other input free; axis_props assumed on the inputs, asserted on the outputs. Parameters shrunk for formal: STEPS = 12, FIRST = 2, FRAME_BITS = 8.
module fec_frame_extract_fv (
    input wire logic clk_i,
    input wire logic rst_i,
    input wire logic [0:0] s_tdata_i,
    input wire logic s_tvalid_i,
    input wire logic m_tready_i,
    input wire logic win_hs_i,
    input wire logic win_last_i,
    input wire logic [2:0] win_tuser_i
);

    logic first_q = 1'b1;
    logic s_tready;
    logic [0:0] m_tdata;
    logic m_tvalid;
    logic m_tlast;
    logic [2:0] m_tuser;
    logic [15:0] flag_ovf;

    always_ff @(posedge clk_i) first_q <= 1'b0;
    always_comb if (first_q) assume (rst_i);

    fec_frame_extract #(
        .STEPS (12),
        .FIRST (2),
        .FRAME_BITS (8)
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
        .win_hs_i (win_hs_i),
        .win_last_i (win_last_i),
        .win_tuser_i (win_tuser_i),
        .flag_ovf_o (flag_ovf)
    );

    axis_props #(.W(1), .UW(1), .IS_INPUT(1'b1)) u_s_in (
        .clk_i (clk_i), .rst_i (rst_i), .tvalid (s_tvalid_i), .tready (s_tready), .tdata (s_tdata_i),
        .tlast (1'b0), .tuser (1'b0)
    );

    axis_props #(.W(1), .UW(3), .IS_INPUT(1'b0)) u_m_out (
        .clk_i (clk_i), .rst_i (rst_i), .tvalid (m_tvalid), .tready (m_tready_i), .tdata (m_tdata),
        .tlast (m_tlast), .tuser (m_tuser)
    );

    // Environment, as rx_chain wires it (fec_frame_extract header): win_* tap the Viterbi's input and s_* is its
    // output, one decided bit per input step, so output bit k never comes before input step k (lag_q > 0 under any
    // offered bit); every window is STEPS steps, win_last on its last; and at most one window plus the traceback
    // depth (< STEPS) is in flight, lag_q <= 2 * STEPS. Under these the flag FIFO never overflows (the header's claim).
    localparam int STEPS = 12;
    logic [7:0] lag_q;   // input steps taken minus output bits taken
    logic [3:0] wpos_q;  // input step within its window

    always_ff @(posedge clk_i) begin
        if (rst_i) begin
            lag_q  <= '0;
            wpos_q <= '0;
        end else begin
            lag_q <= lag_q + 8'(win_hs_i) - 8'(s_tvalid_i && s_tready);
            if (win_hs_i) wpos_q <= (wpos_q == 4'(STEPS - 1)) ? '0 : wpos_q + 4'd1;
        end
    end

    always_comb begin
        if (!rst_i) begin
            assume (!s_tvalid_i || lag_q != '0);
            assume (!win_hs_i || win_last_i == (wpos_q == 4'(STEPS - 1)));
            assume (lag_q <= 8'(2 * STEPS));
            a_no_flag_ovf: assert (flag_ovf == '0);
        end
    end

endmodule

`default_nettype wire
