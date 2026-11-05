`default_nettype none

// Farrow cubic resampler to 2 samples/symbol with the per-rail OQPSK Gardner detector (Phase C; ADR 0002;
// docs/fixed-point.md §Synchronization; bit-true model: model/sync_fixed.py timing() and farrow()).
//
// In: tdata = {Q, I}, s16 each, 256 kS/s (Costas output). Out: tdata = {Q, I}, s16 each, 2 per symbol.
// The position pos (POS_FRAC fraction bits) starts at 1.0. For each output, with k = int(pos) and mu the top MU_W
// fraction bits:
//   y_n = sat(p1 + (v + 1) >>> 1), v from three rounded Horner steps of the Catmull-Rom cubic on x[k-1..k+2]
//   e   = n < 2 ? 0 : clamp(round(r[n-1] (r[n-2] - r[n]) >>> 12), +-ONE),  r = I rail for even n, Q for odd n
//   integ = clamp(integ + ki e, +-limit);   pos += nominal + (integ >>> INTEG_FRAC) + kp e
// The next position depends on this output's error, so outputs are produced one at a time:
//   fill the 4-sample window (adv_q samples still to shift in) | start: partial sums | S1 coefficients
//   | S2..S7 Horner | S8 output | S9 detector terms | S10 product | S11 error | S12 ki e, kp e | S13 integrator
//   | S14 position
// Two splits for timing at 100 MHz: the last rounding and the output over S7/S8 (0.583 ns of slack in one cycle),
// and the coefficients over start/S1 (0.525 ns in one cycle once placed inside sync_top).
// The window and frac_q do not change between start and S14 (s_tready_o is low while adv_q is 0), so the stages
// read them directly. A new output starts only with the output register empty, so a downstream stall holds the
// input. Assumes the step is positive, true for any gains near loop_gains() (it moves 1.78 +- 0.04 samples).
module sync_timing #(
    parameter int W          = 16,  // fixed-point.md §Synchronization
    parameter int ONE        = 4096,  // error clamp; sync_fixed.ONE
    parameter int POS_FRAC   = 24,  // sync_fixed.POS_FRAC
    parameter int MU_W       = 16,  // sync_fixed.MU_BITS
    parameter int INTEG_FRAC = 16,  // sync_fixed.INTEG_FRAC
    parameter int NOM_W      = 28,  // nominal = 29,826,162 (25 bits) at 3.56 sps; room for 8x
    parameter int KP_W       = 16,  // kp = 82 at timing_kp 0.02; room for 100x
    parameter int KI_W       = 24,  // ki = 26,844 at timing_ki default; room for 100x
    parameter int LIM_W      = 40   // limit = 1.95e10 (35 bits) at 1% of nominal; room for 8x nominal x 4x
) (
    input  wire logic                clk_i,
    input  wire logic                rst_i,
    input  wire logic [NOM_W-1:0]    nominal_i,  // sync_fixed.LoopGains.timing_nominal
    input  wire logic [KP_W-1:0]     kp_i,       // .timing_kp
    input  wire logic [KI_W-1:0]     ki_i,       // .timing_ki
    input  wire logic [LIM_W-1:0]    limit_i,    // .timing_limit

    input  wire logic [2*W-1:0]      s_tdata_i,
    input  wire logic                s_tvalid_i,
    output      logic                s_tready_o,

    output      logic [2*W-1:0]      m_tdata_o,
    output      logic                m_tvalid_o,
    input  wire logic                m_tready_i
);

    localparam int CW      = W + 5;               // c2 = 2p0 - 5p1 + 4p2 - p3: |c2| <= 12 * 2^(W-1)
    localparam int TW      = W + 7;               // Horner sums: |v + c| < 2^(W+5), one bit spare
    localparam int MW      = TW + MU_W + 1;       // Horner product, mu as a signed MU_W+1 operand
    localparam int ERR_W   = $clog2(ONE) + 2;     // +-ONE
    localparam int DW      = W + 1;               // r[n-2] - r[n]
    localparam int PW      = W + DW;              // r[n-1] (r[n-2] - r[n])
    localparam int KE_W    = KI_W + ERR_W + 1;
    localparam int PE_W    = KP_W + ERR_W + 1;
    localparam int INTEG_W = LIM_W + 1;
    localparam int SW      = NOM_W + 6;           // frac + nominal + integ >>> INTEG_FRAC + kp e, signed
    localparam int ADV_W   = SW - POS_FRAC;
    localparam int NST     = 14;

    logic signed [W-1:0]       win_q [2][4];      // [rail][x[k-1] .. x[k+2]]
    logic [ADV_W-1:0]          adv_q;
    logic [POS_FRAC-1:0]       frac_q;
    logic signed [INTEG_W-1:0] integ_q;
    logic [NST:1]              st_q;
    logic                      start;
    logic                      take;
    logic                      odd_q;             // parity of n: 0 -> I rail, 1 -> Q rail
    logic                      warm_q;            // n >= 2

    logic signed [CW-1:0]      c1_q [2], c2_q [2], c3_q [2];
    logic signed [CW-1:0]      pa_q [2], pb_q [2], pc_q [2], pd_q [2];  // 2p0-p3, 4p2-5p1, p1-p2, p3-p0
    logic signed [MW-1:0]      m_q [2];
    logic signed [TW-1:0]      t_q [2];
    logic signed [W-1:0]       h1_q [2], h2_q [2];  // r[n-1], r[n-2] per rail
    logic signed [W-1:0]       mid_q;
    logic signed [DW-1:0]      diff_q;
    logic signed [PW-1:0]      prod_q;
    logic signed [ERR_W-1:0]   err_q;
    logic signed [KE_W-1:0]    ke_q;
    logic signed [PE_W-1:0]    pe_q;
    logic signed [W-1:0]       y [2];
    logic signed [MU_W:0]      mu;
    logic signed [SW-1:0]      next_pos;

    assign start      = adv_q == '0 && st_q == '0 && !m_tvalid_o;
    assign s_tready_o = adv_q != '0;
    assign take       = s_tvalid_i && s_tready_o;
    assign mu         = $signed({1'b0, frac_q[POS_FRAC-1 -: MU_W]});
    assign y[0]       = $signed(m_tdata_o[0 +: W]);
    assign y[1]       = $signed(m_tdata_o[W +: W]);
    assign next_pos   = SW'($signed({1'b0, frac_q})) + SW'($signed({1'b0, nominal_i}))
                      + SW'(integ_q >>> INTEG_FRAC) + SW'(pe_q);

    // round(x / 2^MU_W), half up, as the model's (x + half) >> MU_BITS. |x| < 2^(TW-1) 2^MU_W, so it fits TW bits.
    function automatic logic signed [TW-1:0] horner_round(input logic signed [MW-1:0] x);
        return TW'((x + MW'(1 << (MU_W - 1))) >>> MU_W);
    endfunction

    // p1 + (v + 1) >>> 1, saturated to W bits
    function automatic logic signed [W-1:0] farrow_out(input logic signed [W-1:0] p1,
                                                       input logic signed [TW-1:0] v);
        logic signed [TW:0] s;
        s = (TW+1)'(p1) + ((TW+1)'(v) + (TW+1)'(1) >>> 1);
        if (s > (TW+1)'((1 << (W - 1)) - 1))  return {1'b0, {(W-1){1'b1}}};
        else if (s < -(TW+1)'(1 << (W - 1)))  return {1'b1, {(W-1){1'b0}}};
        else                                  return s[W-1:0];
    endfunction

    // round(p / 2^12), clamped to +-ONE: the product of two ONE-scaled values back to ONE scale
    function automatic logic signed [ERR_W-1:0] gardner_err(input logic signed [PW-1:0] p);
        logic signed [PW-1:0] r;
        r = (p + PW'(ONE / 2)) >>> $clog2(ONE);
        if (r > PW'(ONE))        return ERR_W'(ONE);
        else if (r < -PW'(ONE))  return -ERR_W'(ONE);
        else                     return r[ERR_W-1:0];
    endfunction

    function automatic logic signed [INTEG_W-1:0] clamp_integ(input logic signed [INTEG_W:0] x,
                                                              input logic [LIM_W-1:0] lim);
        if (x > $signed({2'b00, lim}))        return INTEG_W'($signed({2'b00, lim}));
        else if (x < -$signed({2'b00, lim}))  return -INTEG_W'($signed({2'b00, lim}));
        else                                  return x[INTEG_W-1:0];
    endfunction

    // Control and loop state
    always_ff @(posedge clk_i) begin
        if (rst_i) begin
            adv_q      <= ADV_W'(4);  // pos = 1.0: the window x[0..3]
            frac_q     <= '0;
            integ_q    <= '0;
            st_q       <= '0;
            odd_q      <= 1'b0;
            warm_q     <= 1'b0;
            m_tvalid_o <= 1'b0;
        end else begin
            st_q <= {st_q[NST-1:1], start};
            if (take) adv_q <= adv_q - ADV_W'(1);
            if (st_q[13]) integ_q <= clamp_integ((INTEG_W+1)'(integ_q) + (INTEG_W+1)'(ke_q), limit_i);
            // S14: integ_q already holds this output's new integrator, as in the model
            if (st_q[14]) begin
                adv_q  <= ADV_W'(next_pos >>> POS_FRAC);
                frac_q <= next_pos[POS_FRAC-1:0];
                odd_q  <= !odd_q;
                warm_q <= warm_q || odd_q;
            end
            if (st_q[8])         m_tvalid_o <= 1'b1;
            else if (m_tready_i) m_tvalid_o <= 1'b0;
        end
    end

    // Datapath
    always_ff @(posedge clk_i) begin
        for (int r = 0; r < 2; r++) begin
            if (take) begin
                win_q[r][0] <= win_q[r][1];
                win_q[r][1] <= win_q[r][2];
                win_q[r][2] <= win_q[r][3];
                win_q[r][3] <= $signed(s_tdata_i[r*W +: W]);
            end
            if (start) begin
                pa_q[r] <= 2 * CW'(win_q[r][0]) - CW'(win_q[r][3]);
                pb_q[r] <= 4 * CW'(win_q[r][2]) - 5 * CW'(win_q[r][1]);
                pc_q[r] <= CW'(win_q[r][1]) - CW'(win_q[r][2]);
                pd_q[r] <= CW'(win_q[r][3]) - CW'(win_q[r][0]);
            end
            if (st_q[1]) begin
                c1_q[r] <= CW'(win_q[r][2]) - CW'(win_q[r][0]);
                c2_q[r] <= pa_q[r] + pb_q[r];
                c3_q[r] <= 3 * pc_q[r] + pd_q[r];
            end
            if (st_q[2]) m_q[r] <= MW'(c3_q[r]) * MW'(mu);
            if (st_q[3]) t_q[r] <= horner_round(m_q[r]) + TW'(c2_q[r]);
            if (st_q[4]) m_q[r] <= MW'(t_q[r]) * MW'(mu);
            if (st_q[5]) t_q[r] <= horner_round(m_q[r]) + TW'(c1_q[r]);
            if (st_q[6]) m_q[r] <= MW'(t_q[r]) * MW'(mu);
            if (st_q[7]) t_q[r] <= horner_round(m_q[r]);
            if (st_q[8]) m_tdata_o[r*W +: W] <= farrow_out(win_q[r][1], t_q[r]);
            if (st_q[14]) begin
                h2_q[r] <= h1_q[r];
                h1_q[r] <= y[r];
            end
        end
        // S9..S12: Gardner on the rail this output belongs to
        mid_q  <= odd_q ? h1_q[1] : h1_q[0];
        diff_q <= odd_q ? DW'(h2_q[1]) - DW'(y[1]) : DW'(h2_q[0]) - DW'(y[0]);
        prod_q <= PW'(mid_q) * PW'(diff_q);
        err_q  <= warm_q ? gardner_err(prod_q) : '0;
        ke_q   <= $signed({1'b0, ki_i}) * err_q;
        pe_q   <= $signed({1'b0, kp_i}) * err_q;
    end

endmodule

`default_nettype wire
