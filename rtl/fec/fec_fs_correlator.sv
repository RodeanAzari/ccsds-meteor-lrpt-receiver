`default_nettype none

// Encoded-ASM correlators for frame sync (buildplan §3.5, ADR 0010; bit-true model: model/framesync_fixed.py hits()).
//
// For each position n and hypothesis h: c[h][n] = sum_k pattern[h][k] * v[n+k], k < PATTERN_LEN, v = 2u - 15, and
// level[n] = sum_k |v[n+k]|. hit[h] = |c[h]| * 64 > thr64 * level. Transposed form: one register per tap, and each
// symbol adds ±v into every partial sum, so each register sits behind one small add (no adder tree to pipeline).
//
// Advances only on en_i (the frame sync's input handshake). After the beat that consumed symbol t, the sums hold
// position t - PATTERN_LEN + 1 and hit_o (registered: the threshold multiply and compare get their own stage) holds
// position t - PATTERN_LEN. The first PATTERN_LEN beats leave partial results, which the caller ignores.
module fec_fs_correlator #(
    parameter int    SOFT_BITS    = 4,                  // ADR 0005
    parameter int    PATTERN_LEN  = 52,                 // 64 encoded ASM symbols less ASM_TRANSIENT_SYMBOLS (12)
    parameter int    HYPS         = 4,                  // receiver._hypothesis_patterns()
    parameter int    THR_BITS     = 6,                  // framesync_fixed.THR_FRAC: threshold in 1/64ths
    parameter string PATTERN_FILE = "asm_patterns.mem"  // scripts/gen_rtl_tables.py: bit k set = +1
) (
    input  wire logic                 clk_i,
    input  wire logic                 rst_i,
    input  wire logic                 en_i,
    input  wire logic [SOFT_BITS-1:0] u_i,
    input  wire logic [THR_BITS-1:0]  thr64_i,  // control register: 48 = 0.75 (RxConfig.sync_threshold)
    output      logic [HYPS-1:0]      hit_o
);

    localparam int VMAX  = (1 << SOFT_BITS) - 1;                  // |v| <= 15, v = 2u - 15 odd
    localparam int SUM_W = $clog2(PATTERN_LEN * VMAX + 1) + 1;    // signed sum of PATTERN_LEN terms: 11 bits
    localparam int CMP_W = SUM_W + THR_BITS;                      // |c| << THR_BITS and thr64 * level

    logic [PATTERN_LEN-1:0] pattern [HYPS];
    initial $readmemh(PATTERN_FILE, pattern);  // constant table (CLAUDE.md §5.1: ROM init)

    logic signed [SOFT_BITS:0]   v;
    logic        [SOFT_BITS-1:0] mag;
    always_comb begin
        v   = $signed({~u_i[SOFT_BITS-1], u_i[SOFT_BITS-2:0], 1'b1});  // offset binary 2u + 1 less 2^SOFT_BITS
        mag = v < 0 ? SOFT_BITS'(-v) : SOFT_BITS'(v);
    end

    // acc[h][k] = partial sum over pattern taps 0..k, aligned so that tap k meets the newest symbol.
    logic signed [SUM_W-1:0] acc   [HYPS][PATTERN_LEN-1];
    logic        [SUM_W-1:0] lacc  [PATTERN_LEN-1];
    logic signed [SUM_W-1:0] corr_q [HYPS];
    logic        [SUM_W-1:0] level_q;

    function automatic logic signed [SUM_W-1:0] term(input logic plus, input logic signed [SOFT_BITS:0] x);
        return plus ? SUM_W'(x) : -SUM_W'(x);
    endfunction

    always_ff @(posedge clk_i) begin
        if (rst_i) begin
            for (int h = 0; h < HYPS; h++) begin
                for (int k = 0; k < PATTERN_LEN - 1; k++) acc[h][k] <= '0;
                corr_q[h] <= '0;
            end
            for (int k = 0; k < PATTERN_LEN - 1; k++) lacc[k] <= '0;
            level_q <= '0;
        end else if (en_i) begin
            for (int h = 0; h < HYPS; h++) begin
                acc[h][0] <= term(pattern[h][0], v);
                for (int k = 1; k < PATTERN_LEN - 1; k++) acc[h][k] <= acc[h][k-1] + term(pattern[h][k], v);
                corr_q[h] <= acc[h][PATTERN_LEN-2] + term(pattern[h][PATTERN_LEN-1], v);
            end
            lacc[0] <= SUM_W'(mag);
            for (int k = 1; k < PATTERN_LEN - 1; k++) lacc[k] <= lacc[k-1] + SUM_W'(mag);
            level_q <= lacc[PATTERN_LEN-2] + SUM_W'(mag);
        end
    end

    // Threshold: |c| * 64 > thr64 * level, both below 2^CMP_W.
    logic [SUM_W-1:0] mag_c [HYPS];
    logic [HYPS-1:0]  hit_d;
    always_comb begin
        for (int h = 0; h < HYPS; h++) begin
            mag_c[h] = corr_q[h] < 0 ? SUM_W'(-corr_q[h]) : SUM_W'(corr_q[h]);
            hit_d[h] = (CMP_W'(mag_c[h]) << THR_BITS) > CMP_W'(thr64_i) * CMP_W'(level_q);
        end
    end

    always_ff @(posedge clk_i) begin
        if (rst_i)     hit_o <= '0;
        else if (en_i) hit_o <= hit_d;
    end

endmodule

`default_nettype wire
