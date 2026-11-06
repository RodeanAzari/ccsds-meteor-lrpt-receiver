`default_nettype none

// One add-compare-select with modulo path metrics (ADR 0006; bit-true model: model/viterbi_fixed.py acs()).
//
// Candidates m0 = pm0 + bm0 and m1 = pm1 + bm1, both mod 2^PM_BITS. Branch 1 wins when m1 - m0, mod 2^PM_BITS, is
// negative as a PM_BITS-bit two's-complement number. That compare is valid while the candidates' spread is below
// 2^(PM_BITS-1), which the width guarantees (ADR 0006). A tie keeps branch 0, as the model does. Combinational.
module fec_acs #(
    parameter int PM_BITS = 9,  // ADR 0006: viterbi_fixed.path_metric_bits(4)
    parameter int BM_BITS = 5   // fec_bm: SOFT_BITS + 1
) (
    input  wire logic [PM_BITS-1:0] pm0_i,
    input  wire logic [PM_BITS-1:0] pm1_i,
    input  wire logic [BM_BITS-1:0] bm0_i,
    input  wire logic [BM_BITS-1:0] bm1_i,
    output      logic [PM_BITS-1:0] pm_o,
    output      logic               dec_o  // 1: the survivor comes from predecessor 1
);

    logic [PM_BITS-1:0] m0, m1, diff;

    always_comb begin
        m0    = pm0_i + PM_BITS'(bm0_i);
        m1    = pm1_i + PM_BITS'(bm1_i);
        diff  = m1 - m0;
        dec_o = diff[PM_BITS-1];
        pm_o  = dec_o ? m1 : m0;
    end

endmodule

`default_nettype wire
