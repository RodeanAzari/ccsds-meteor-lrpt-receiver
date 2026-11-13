`default_nettype none

// Fourth-order Costas loop (Phase C; ADR 0002; docs/fixed-point.md §Synchronization; bit-true model:
// model/sync_fixed.py costas()).
//
// In/out: tdata = {Q, I}, each s16 in ONE units (AGC output), 256 kS/s. Per sample, with phase p (u32) and
// frequency f (FREQ_FRAC extra fraction bits):
//   y   = sat(round((x_i + j x_q)(cos p - j sin p) >> 15))        cos/sin from the DDC's quarter-wave table
//   e   = clamp(sgn(y_i) y_q - sgn(y_q) y_i, +-ONE)               sgn(0) = -1, as the model's "> 0"
//   f   = clamp(f + ki e, +-fmax);   p += (f >>> FREQ_FRAC) + kp e   (mod 2^32)
// The phase for sample n+1 depends on sample n, so one sample is in flight:
//   take | S1 table read | S2 quadrant mirror | S3 products | S4 round, saturate -> output | S5 detector terms
//   | S6 error, clamped | S7 ki e, kp e | S8 frequency | S9 phase
// The detector is split over S5/S6: in one cycle it left only 0.5 ns of slack at 100 MHz.
// The input is accepted only when idle with the output register empty, so a downstream stall holds the input.
// The gains are control registers (CLAUDE.md §3.1), computed by sync_fixed.loop_gains().
module sync_costas #(
    parameter int    W         = 16,   // fixed-point.md §Synchronization
    parameter int    ONE       = 4096, // error clamp; sync_fixed.ONE
    parameter int    PHASE_W   = 32,   // ddc_fixed.PHASE_BITS; ADR 0003
    parameter int    LUT_PH_W  = 12,   // ddc_fixed.LUT_PHASE_BITS; ADR 0003
    parameter int    NCO_W     = 16,   // ddc_fixed.NCO_BITS; ADR 0003
    parameter int    FREQ_FRAC = 16,   // sync_fixed.FREQ_FRAC
    parameter int    KP_W      = 16,   // kp = 471 at costas_bw 0.001; room for 100x
    parameter int    KI_W      = 24,   // ki = 43,686 at costas_bw 0.001; room for 100x (ki ~ bw^2)
    parameter string LUT_FILE  = "nco_lut.mem"  // the DDC's table; scripts/gen_rtl_tables.py
) (
    input  wire logic                           clk_i,
    input  wire logic                           rst_i,
    input  wire logic [KP_W-1:0]                kp_i,     // sync_fixed.LoopGains.costas_kp
    input  wire logic [KI_W-1:0]                ki_i,     // .costas_ki
    input  wire logic [PHASE_W+FREQ_FRAC-2:0]   fmax_i,   // .costas_max

    input  wire logic [2*W-1:0]                 s_tdata_i,
    input  wire logic                           s_tvalid_i,
    output      logic                           s_tready_o,

    output      logic [2*W-1:0]                 m_tdata_o,
    output      logic                           m_tvalid_o,
    input  wire logic                           m_tready_i
);

    localparam int ADDR_W = LUT_PH_W - 2;
    localparam int ROT_SH = NCO_W - 1;                 // >> 15: the table's peak is 2^15 - 1
    localparam int PROD_W = W + NCO_W + 1;             // sum of two s16 x s16 products
    localparam int ERR_W  = $clog2(ONE) + 2;           // +-ONE
    localparam int FREQ_W = PHASE_W + FREQ_FRAC;       // s48
    localparam int KE_W   = KI_W + ERR_W + 1;          // ki e, signed
    localparam int PE_W   = KP_W + ERR_W + 1;          // kp e, signed

    logic signed [NCO_W-1:0] lut [2**ADDR_W];
    initial $readmemh(LUT_FILE, lut);

    logic [9:1]               st_q;
    logic                     take;
    logic [PHASE_W-1:0]       phase_q;
    logic signed [FREQ_W-1:0] freq_q;

    logic signed [W-1:0]      x_q [2];          // {I, Q}
    logic [1:0]               quad0_q, quad1_q;
    logic [ADDR_W-1:0]        addr0_q;
    logic signed [NCO_W-1:0]  a1_q, b1_q, cos2_q, sin2_q;
    logic signed [PROD_W-1:0] re3_q, im3_q;
    logic signed [W:0]        tq5_q, ti5_q;     // sgn(yi) yq, sgn(yq) yi
    logic signed [ERR_W-1:0]  err6_q;
    logic signed [KE_W-1:0]   ke7_q;
    logic signed [PE_W-1:0]   pe7_q;
    logic signed [W-1:0]      yi, yq;

    assign s_tready_o = st_q == '0 && !m_tvalid_o;
    assign take       = s_tvalid_i && s_tready_o;
    assign yi         = $signed(m_tdata_o[0 +: W]);
    assign yq         = $signed(m_tdata_o[W +: W]);

    function automatic logic signed [W-1:0] sat_round(input logic signed [PROD_W-1:0] x);
        logic signed [PROD_W-1:0] r;
        r = (x + PROD_W'(1 << (ROT_SH - 1))) >>> ROT_SH;
        if (r > PROD_W'((1 << (W - 1)) - 1))   return {1'b0, {(W-1){1'b1}}};
        else if (r < -PROD_W'(1 << (W - 1)))   return {1'b1, {(W-1){1'b0}}};
        else                                   return r[W-1:0];
    endfunction

    // Fourth-order phase detector, clamped to +-ONE (|raw| <= 2^16 before the clamp)
    function automatic logic signed [ERR_W-1:0] clamp_err(input logic signed [W+1:0] e);
        if (e > (W+2)'(ONE))        return ERR_W'(ONE);
        else if (e < -(W+2)'(ONE))  return -ERR_W'(ONE);
        else                        return e[ERR_W-1:0];
    endfunction

    function automatic logic signed [FREQ_W-1:0] clamp_freq(input logic signed [FREQ_W:0] f,
                                                             input logic [FREQ_W-2:0] fmax);
        if (f > $signed({2'b00, fmax}))        return FREQ_W'($signed({2'b00, fmax}));
        else if (f < -$signed({2'b00, fmax}))  return -FREQ_W'($signed({2'b00, fmax}));
        else                                   return f[FREQ_W-1:0];
    endfunction

    // Control and loop state
    always_ff @(posedge clk_i) begin
        if (rst_i) begin
            st_q       <= '0;
            m_tvalid_o <= 1'b0;
            phase_q    <= '0;
            freq_q     <= '0;
        end else begin
            st_q <= {st_q[8:1], take};
            if (st_q[8]) freq_q <= clamp_freq((FREQ_W+1)'(freq_q) + (FREQ_W+1)'(ke7_q), fmax_i);
            // S9: freq_q already holds this sample's new frequency, as in the model
            if (st_q[9]) phase_q <= phase_q + PHASE_W'(freq_q >>> FREQ_FRAC) + PHASE_W'(pe7_q);
            if (st_q[4])         m_tvalid_o <= 1'b1;
            else if (m_tready_i) m_tvalid_o <= 1'b0;
        end
    end

    // Datapath
    always_ff @(posedge clk_i) begin
        if (take) begin
            x_q[0]  <= $signed(s_tdata_i[0 +: W]);
            x_q[1]  <= $signed(s_tdata_i[W +: W]);
            // table phase: top LUT_PH_W bits of the phase, truncated (ADR 0003)
            quad0_q <= phase_q[PHASE_W-1 -: 2];
            addr0_q <= phase_q[PHASE_W-3 -: ADDR_W];
        end
        // S1
        quad1_q <= quad0_q;
        a1_q    <= lut[addr0_q];
        b1_q    <= lut[~addr0_q];  // last - addr
        // S2: mirror the quarter wave into four quadrants (as ddc_nco_mixer)
        unique case (quad1_q)
            2'd0: begin sin2_q <=  a1_q; cos2_q <=  b1_q; end
            2'd1: begin sin2_q <=  b1_q; cos2_q <= -a1_q; end
            2'd2: begin sin2_q <= -a1_q; cos2_q <= -b1_q; end
            2'd3: begin sin2_q <= -b1_q; cos2_q <=  a1_q; end
        endcase
        // S3: (i + jq)(cos - j sin)
        re3_q <= PROD_W'(x_q[0] * cos2_q) + PROD_W'(x_q[1] * sin2_q);
        im3_q <= PROD_W'(x_q[1] * cos2_q) - PROD_W'(x_q[0] * sin2_q);
        // S4
        if (st_q[4]) m_tdata_o <= {sat_round(im3_q), sat_round(re3_q)};
        // S5: sgn(0) = -1, as the model's "> 0"
        tq5_q  <= yi > 0 ? (W+1)'(yq) : -(W+1)'(yq);
        ti5_q  <= yq > 0 ? (W+1)'(yi) : -(W+1)'(yi);
        // S6, S7
        err6_q <= clamp_err((W+2)'(tq5_q) - (W+2)'(ti5_q));
        ke7_q  <= $signed({1'b0, ki_i}) * err6_q;
        pe7_q  <= $signed({1'b0, kp_i}) * err6_q;
    end

`ifndef SYNTHESIS
    // Coverage bins (make cov, docs/coverage.md): backpressure on each interface.
    cov_bp_s: cover property (@(posedge clk_i) disable iff (rst_i) s_tvalid_i && !s_tready_o);
    cov_bp_m: cover property (@(posedge clk_i) disable iff (rst_i) m_tvalid_o && !m_tready_i);
`endif

endmodule

`default_nettype wire
