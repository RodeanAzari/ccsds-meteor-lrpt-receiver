`default_nettype none

// Frame bits to CADU bytes: ASM check, derandomizer, Reed-Solomon ×4 (ADR 0012; bit-true model:
// model/coding.py frame_to_cadu() after NRZ-M, model/cadu_fixed.py CaduOut).
//
// One 1,024-byte buffer, one frame at a time, three phases:
//   RX:  frame bits in (MSB of each byte first). Bits 0..31: ASM bit errors against ASM. Bits 32..: XOR with the
//        CCSDS PN (h(x) = x^8+x^7+x^5+x^3+1, all ones at bit 32; coding.pn_table()). Packed into bytes, written in
//        arrival order.
//   RS:  the body read codeword by codeword (byte 4 + 4n + b, b = 0..3, n = 0..254) into fpga-rs-core rs_decoder,
//        its output written back to the same addresses; per codeword {fail, corrected} kept.
//   TX:  bytes 0..1023 out with the status on tuser; then RX again (s_tready is low outside RX: backpressure into
//        the Viterbi, which at ~96 clocks per bit has ~400x the time this takes; ADR 0012).
//
// Out: m_tdata = byte, m_tlast on byte 1023, m_tuser = status, constant over the CADU (model/cadu_fixed.py):
//   [2:0] {flywheel, swap, alternate} (from the frame's first bit), [8:3] ASM bit errors,
//   [14:9], [20:15], [26:21], [32:27] codewords 0..3: {fail, corrected[4:0]} (count 0 when fail).
// Framing: FRAME_BITS bits counted from reset; s_tlast is checked against the count, each mismatch counted in
// len_err_o, the count stays the framing.
module fec_cadu #(
    parameter int          FRAME_BITS = 8192,          // model/coding.py CADU_BITS
    parameter logic [31:0] ASM        = 32'h1ACFFC1D,  // model/coding.py ASM, docs/signal-spec.md
    parameter int          COUNT_BITS = 16
) (
    input  wire logic                  clk_i,
    input  wire logic                  rst_i,

    input  wire logic                  s_tdata_i,
    input  wire logic [2:0]            s_tuser_i,  // {flywheel, swap, alternate}
    input  wire logic                  s_tlast_i,
    input  wire logic                  s_tvalid_i,
    output      logic                  s_tready_o,

    output      logic [7:0]            m_tdata_o,
    output      logic [32:0]           m_tuser_o,
    output      logic                  m_tlast_o,
    output      logic                  m_tvalid_o,
    input  wire logic                  m_tready_i,

    output      logic [COUNT_BITS-1:0] len_err_o
);

    localparam int BYTES      = FRAME_BITS / 8;  // 1,024
    localparam int ADDR_BITS  = $clog2(BYTES);
    localparam int BIT_BITS   = $clog2(FRAME_BITS);
    localparam int INTERLEAVE = 4;               // docs/signal-spec.md: RS interleave depth
    localparam int RS_N       = 255;             // docs/signal-spec.md: RS(255,223)
    localparam int RS_CNT     = $clog2(RS_N + 1);
    localparam int ASM_BITS   = 32;
    // fpga-rs-core parameters for CCSDS (docs/signal-spec.md §Reed-Solomon; fpga-rs-core model/vectors.py CCSDS)
    localparam int RS_M = 8, RS_POLY = 'h187, RS_FCR = 112, RS_PRIM = 11, RS_NROOTS = 32;

    typedef enum logic [1:0] {RX, RS, TX} phase_t;
    phase_t phase_q;

    logic [7:0]           mem [BYTES];
    logic [ADDR_BITS-1:0] rd_addr, wr_addr;
    logic [7:0]           rd_data, wr_data;
    logic                 wr_en;

    always_ff @(posedge clk_i) begin
        if (wr_en) mem[wr_addr] <= wr_data;
    end
    assign rd_data = mem[rd_addr];

    // ---- RX ------------------------------------------------------------------------------------------------------
    logic [BIT_BITS-1:0] bit_q;
    logic [6:0]          sh_q;        // the byte's first 7 bits
    logic [7:0]          pn_q;        // pn_q[0] is the PN bit for the current body bit
    logic [5:0]          asm_err_q;
    logic [2:0]          flags_q;
    logic                rx_accept, rx_bit, rx_last;

    assign s_tready_o = phase_q == RX;
    assign rx_accept  = s_tvalid_i && s_tready_o;
    assign rx_last    = bit_q == BIT_BITS'(FRAME_BITS - 1);
    assign rx_bit     = bit_q < BIT_BITS'(ASM_BITS) ? s_tdata_i : s_tdata_i ^ pn_q[0];

    // ---- RS ------------------------------------------------------------------------------------------------------
    logic [1:0]           fc_q, wc_q;   // codeword being fed / written back
    logic [7:0]           fn_q, wn_q;   // byte within it
    logic                 feeding_q;
    logic                 rs_s_ready, rs_m_valid, rs_m_last;
    logic [7:0]           rs_m_data;
    logic [RS_CNT:0]      rs_m_user;    // {fail, corrected}
    // Always 0: feed_last comes from the same N-symbol count the decoder frames by.
    /* verilator lint_off UNUSEDSIGNAL */
    logic [15:0]          rs_len_err;
    /* verilator lint_on UNUSEDSIGNAL */
    logic [5:0]           rs_stat_q [INTERLEAVE];
    logic                 feed_hs, feed_last;

    assign feed_hs   = feeding_q && rs_s_ready;
    assign feed_last = fn_q == 8'(RS_N - 1);

    rs_decoder #(
        .M         (RS_M),
        .PRIM_POLY (RS_POLY),
        .FCR       (RS_FCR),
        .PRIM      (RS_PRIM),
        .NROOTS    (RS_NROOTS),
        .N         (RS_N)
    ) u_rs (
        .clk_i           (clk_i),
        .rst_i           (rst_i),
        .s_axis_tdata_i  (rd_data),
        .s_axis_tvalid_i (feeding_q),
        .s_axis_tready_o (rs_s_ready),
        .s_axis_tlast_i  (feed_last),
        .m_axis_tdata_o  (rs_m_data),
        .m_axis_tvalid_o (rs_m_valid),
        .m_axis_tready_i (1'b1),        // the write port is free in the RS phase
        .m_axis_tlast_o  (rs_m_last),
        .m_axis_tuser_o  (rs_m_user),
        .len_err_o       (rs_len_err)
    );

    // ---- TX ------------------------------------------------------------------------------------------------------
    logic [ADDR_BITS-1:0] tx_q;
    logic                 tx_hs;

    assign m_tvalid_o = phase_q == TX;
    assign m_tdata_o  = rd_data;
    assign m_tlast_o  = tx_q == ADDR_BITS'(BYTES - 1);
    assign m_tuser_o  = {rs_stat_q[3], rs_stat_q[2], rs_stat_q[1], rs_stat_q[0], asm_err_q, flags_q};
    assign tx_hs      = m_tvalid_o && m_tready_i;

    // ---- the buffer's ports ----------------------------------------------------------------------------------------
    always_comb begin
        rd_addr = tx_q;
        if (phase_q == RS) rd_addr = ADDR_BITS'(4 + 4 * int'(fn_q) + int'(fc_q));
        wr_en   = 1'b0;
        wr_addr = ADDR_BITS'(bit_q >> 3);
        wr_data = {sh_q, rx_bit};
        if (phase_q == RX) begin
            wr_en = rx_accept && bit_q[2:0] == 3'd7;
        end else if (phase_q == RS) begin
            wr_en   = rs_m_valid;
            wr_addr = ADDR_BITS'(4 + 4 * int'(wn_q) + int'(wc_q));
            wr_data = rs_m_data;
        end
    end

    always_ff @(posedge clk_i) begin
        if (rx_accept) begin
            sh_q <= {sh_q[5:0], rx_bit};
            if (bit_q == '0) begin
                flags_q   <= s_tuser_i;
                asm_err_q <= 6'(s_tdata_i ^ ASM[ASM_BITS-1]);
            end else if (bit_q < BIT_BITS'(ASM_BITS)) begin
                asm_err_q <= asm_err_q + 6'(s_tdata_i ^ ASM[ASM_BITS-1-int'(bit_q)]);
            end
            // The PN restarts at the body's first bit: pn_q holds all ones while bit 32 is being used.
            if (bit_q < BIT_BITS'(ASM_BITS)) pn_q <= 8'hFF;
            else pn_q <= {pn_q[0] ^ pn_q[3] ^ pn_q[5] ^ pn_q[7], pn_q[7:1]};
        end
        if (rs_m_valid && rs_m_last) rs_stat_q[wc_q] <= {rs_m_user[RS_CNT], rs_m_user[4:0]};
    end

    always_ff @(posedge clk_i) begin
        if (rst_i) begin
            phase_q   <= RX;
            bit_q     <= '0;
            fc_q      <= '0;
            fn_q      <= '0;
            wc_q      <= '0;
            wn_q      <= '0;
            feeding_q <= 1'b0;
            tx_q      <= '0;
            len_err_o <= '0;
        end else begin
            case (phase_q)
                RX: if (rx_accept) begin
                    bit_q <= rx_last ? '0 : bit_q + BIT_BITS'(1);
                    if (s_tlast_i != rx_last && len_err_o != '1) len_err_o <= len_err_o + COUNT_BITS'(1);
                    if (rx_last) begin
                        phase_q   <= RS;
                        feeding_q <= 1'b1;
                    end
                end
                RS: begin
                    if (feed_hs) begin
                        fn_q <= feed_last ? '0 : fn_q + 8'd1;
                        if (feed_last) begin
                            fc_q <= fc_q + 2'd1;
                            if (fc_q == 2'(INTERLEAVE - 1)) feeding_q <= 1'b0;
                        end
                    end
                    if (rs_m_valid) begin
                        wn_q <= rs_m_last ? '0 : wn_q + 8'd1;
                        if (rs_m_last) begin
                            wc_q <= wc_q + 2'd1;
                            if (wc_q == 2'(INTERLEAVE - 1)) phase_q <= TX;
                        end
                    end
                end
                TX: if (tx_hs) begin
                    tx_q <= m_tlast_o ? '0 : tx_q + ADDR_BITS'(1);
                    if (m_tlast_o) phase_q <= RX;
                end
                default: phase_q <= RX;
            endcase
        end
    end

endmodule

`default_nettype wire
