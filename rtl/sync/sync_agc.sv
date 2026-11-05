`default_nettype none

// Feedback AGC on I^2 + Q^2 (Phase C; docs/fixed-point.md §Synchronization; bit-true model: model/sync_fixed.py agc()).
//
// In/out: tdata = {Q, I}, each s16, 256 kS/s. Per sample n, with gain g (u20, GAIN_FRAC fraction bits):
//   y = sat(round(x * g >> GAIN_FRAC))                                   (output rail rms -> ONE)
//   g = clamp(g + round((2*ONE^2 - yi^2 - yq^2) >> SHIFT), 1, 2^GAIN_W - 1)
// The gain update uses the output just produced, so sample n+1 must wait for it. One sample at a time:
//   take | S1 x*g | S2 round, saturate -> output | S3 yi^2 + yq^2 | S4 error term | S5 gain update
// The input is accepted only when idle with the output register empty, so a downstream stall holds the input.
// 6 clocks per sample of the ~390 a 100 MHz clock has per 256 kS/s sample.
module sync_agc #(
    parameter int W         = 16,     // fixed-point.md §RRC output / §Synchronization
    parameter int GAIN_W    = 20,     // u20; sync_fixed.AGC_GAIN_BITS
    parameter int GAIN_FRAC = 12,     // sync_fixed.AGC_FRAC
    parameter int SHIFT     = 24,     // loop gain 2^-SHIFT; sync_fixed.AGC_SHIFT
    parameter int ONE       = 4096,   // target rail rms; sync_fixed.ONE
    parameter int GAIN0     = 4096    // gain after reset (1.0); agc(gain0) default
) (
    input  wire logic           clk_i,
    input  wire logic           rst_i,

    input  wire logic [2*W-1:0] s_tdata_i,
    input  wire logic           s_tvalid_i,
    output      logic           s_tready_o,

    output      logic [2*W-1:0] m_tdata_o,
    output      logic           m_tvalid_o,
    input  wire logic           m_tready_i
);

    localparam int PROD_W = W + GAIN_W + 1;   // s16 * u20 (as s21)
    localparam int POW_W  = 2 * W + 1;        // yi^2 + yq^2 <= 2^31: u32, kept signed
    localparam int ERR_W  = POW_W + 1;        // 2*ONE^2 - p
    localparam logic signed [ERR_W-1:0] TARGET = ERR_W'(2 * ONE * ONE);  // sync_fixed.AGC_TARGET
    localparam logic [GAIN_W-1:0]       GMAX   = '1;

    logic [GAIN_W-1:0]        gain_q;
    logic signed [W-1:0]      x_q    [2];
    logic signed [PROD_W-1:0] prod_q [2];
    logic signed [POW_W-1:0]  pow_q;
    logic signed [ERR_W-1:0]  step_q;
    logic [5:1]               st_q;    // one-hot stage valid, S1..S5
    logic                     take;

    assign s_tready_o = st_q == '0 && !m_tvalid_o;
    assign take       = s_tvalid_i && s_tready_o;

    function automatic logic signed [W-1:0] sat_round(input logic signed [PROD_W-1:0] p);
        logic signed [PROD_W-1:0] r;
        r = (p + PROD_W'(1 << (GAIN_FRAC - 1))) >>> GAIN_FRAC;
        if (r > PROD_W'((1 << (W - 1)) - 1))   return {1'b0, {(W-1){1'b1}}};
        else if (r < -PROD_W'(1 << (W - 1)))   return {1'b1, {(W-1){1'b0}}};
        else                                   return r[W-1:0];
    endfunction

    // g + step, clamped to [1, GMAX]; step is small, so GAIN_W + 2 bits hold the sum
    function automatic logic [GAIN_W-1:0] clamp_gain(input logic signed [ERR_W-1:0] s, input logic [GAIN_W-1:0] g);
        logic signed [ERR_W-1:0] t;
        t = ERR_W'({1'b0, g}) + s;
        if (t < ERR_W'(1))                     return GAIN_W'(1);
        else if (t > ERR_W'({1'b0, GMAX}))     return GMAX;
        else                                   return t[GAIN_W-1:0];
    endfunction

    // Control and gain
    always_ff @(posedge clk_i) begin
        if (rst_i) begin
            st_q       <= '0;
            m_tvalid_o <= 1'b0;
            gain_q     <= GAIN_W'(GAIN0);
        end else begin
            st_q <= {st_q[4:1], take};
            if (st_q[5]) gain_q <= clamp_gain(step_q, gain_q);
            if (st_q[2])         m_tvalid_o <= 1'b1;
            else if (m_tready_i) m_tvalid_o <= 1'b0;
        end
    end

    // Datapath
    always_ff @(posedge clk_i) begin
        if (take) begin
            x_q[0] <= $signed(s_tdata_i[0 +: W]);
            x_q[1] <= $signed(s_tdata_i[W +: W]);
        end
        for (int r = 0; r < 2; r++) prod_q[r] <= x_q[r] * $signed({1'b0, gain_q});
        if (st_q[2]) m_tdata_o <= {sat_round(prod_q[1]), sat_round(prod_q[0])};
        pow_q  <= POW_W'($signed(m_tdata_o[0 +: W]) * $signed(m_tdata_o[0 +: W]))
                + POW_W'($signed(m_tdata_o[W +: W]) * $signed(m_tdata_o[W +: W]));
        step_q <= (TARGET - ERR_W'(pow_q) + ERR_W'(1 << (SHIFT - 1))) >>> SHIFT;
    end

endmodule

`default_nettype wire
