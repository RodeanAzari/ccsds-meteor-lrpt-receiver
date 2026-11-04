`default_nettype none

// CIC droop-compensation FIR, both rails (Phase B; ADR 0004; docs/fixed-point.md §DDC; bit-true model:
// model/ddc_fixed.py comp_fir()).
//
// In/out: tdata = {Q, I}, each s16, 256 kS/s.   y[n] = sat(round(sum_k h[k] x[n-k] >> COEF_FRAC)), x[<0] = 0.
// One multiplier per rail, time-shared over the taps: NTAPS + 3 cycles per sample, about 34 of the ~390 a 100 MHz
// clock has per 256 kS/s sample. The input is accepted only when idle with the output register empty, so a stall
// downstream holds the input; nothing is dropped.
// Pipeline per tap: select x[n-k] and h[k] | multiply | accumulate.
module ddc_comp_fir #(
    parameter int    W         = 16,  // fixed-point.md §DDC
    parameter int    NTAPS     = 31,  // RxConfig.comp_taps; ADR 0004
    parameter int    COEF_W    = 18,  // s1.17, DSP48E1 B port; fixed-point.md §DDC
    parameter int    COEF_FRAC = 17,  // fixed-point.md §DDC
    parameter int    ACC_W     = 40,  // >= W + COEF_W + log2(NTAPS) = 39; fixed-point.md §DDC
    parameter string TAP_FILE  = "comp_fir_taps.mem"  // written by scripts/gen_rtl_tables.py from model comp_taps()
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

    localparam int CNT_W  = $clog2(NTAPS + 1);
    localparam int PROD_W = W + COEF_W;

    logic signed [COEF_W-1:0] taps [NTAPS];
    initial $readmemh(TAP_FILE, taps);

    logic signed [W-1:0]      hist_q [2][NTAPS];  // hist_q[r][k] = x[n-k]
    logic [CNT_W-1:0]         cnt_q;
    logic                     busy_q, v1_q, v2_q;
    logic signed [W-1:0]      sel_q  [2];
    logic signed [COEF_W-1:0] tap_q;
    logic signed [PROD_W-1:0] prod_q [2];
    logic signed [ACC_W-1:0]  acc_q  [2];
    logic                     take, done;

    assign s_tready_o = !busy_q && !m_tvalid_o;
    assign take       = s_tvalid_i && s_tready_o;
    assign done       = busy_q && cnt_q == CNT_W'(NTAPS) && !v1_q && !v2_q;

    function automatic logic signed [W-1:0] sat_round(input logic signed [ACC_W-1:0] x);
        logic signed [ACC_W-1:0] r;
        r = (x + ACC_W'(1 << (COEF_FRAC - 1))) >>> COEF_FRAC;
        if (r > ACC_W'((1 << (W - 1)) - 1))      return {1'b0, {(W-1){1'b1}}};
        else if (r < -ACC_W'(1 << (W - 1)))      return {1'b1, {(W-1){1'b0}}};
        else                                     return r[W-1:0];
    endfunction

    // Control and history (history is reset: the model starts from x[<0] = 0)
    always_ff @(posedge clk_i) begin
        if (rst_i) begin
            busy_q     <= 1'b0;
            cnt_q      <= '0;
            v1_q       <= 1'b0;
            v2_q       <= 1'b0;
            m_tvalid_o <= 1'b0;
            for (int r = 0; r < 2; r++)
                for (int k = 0; k < NTAPS; k++) hist_q[r][k] <= '0;
        end else begin
            v1_q <= busy_q && cnt_q < CNT_W'(NTAPS);
            v2_q <= v1_q;
            if (take) begin
                for (int r = 0; r < 2; r++) begin
                    hist_q[r][0] <= $signed(s_tdata_i[r*W +: W]);
                    for (int k = 1; k < NTAPS; k++) hist_q[r][k] <= hist_q[r][k-1];
                end
                busy_q <= 1'b1;
                cnt_q  <= '0;
            end else if (busy_q && cnt_q < CNT_W'(NTAPS)) begin
                cnt_q <= cnt_q + 1'b1;
            end
            if (done)            busy_q <= 1'b0;
            if (done)            m_tvalid_o <= 1'b1;
            else if (m_tready_i) m_tvalid_o <= 1'b0;
        end
    end

    // Datapath
    always_ff @(posedge clk_i) begin
        if (cnt_q < CNT_W'(NTAPS)) tap_q <= taps[cnt_q];
        for (int r = 0; r < 2; r++) begin
            if (cnt_q < CNT_W'(NTAPS)) sel_q[r] <= hist_q[r][cnt_q];
            prod_q[r] <= sel_q[r] * tap_q;
            if (take)      acc_q[r] <= '0;
            else if (v2_q) acc_q[r] <= acc_q[r] + ACC_W'(prod_q[r]);
        end
        if (done) m_tdata_o <= {sat_round(acc_q[1]), sat_round(acc_q[0])};
    end

endmodule

`default_nettype wire
