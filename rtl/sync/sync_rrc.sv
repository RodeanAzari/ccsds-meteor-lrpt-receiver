`default_nettype none

// RRC matched filter, both rails (Phase C; docs/fixed-point.md §RRC; bit-true model: model/rrc_fixed.py).
//
// In/out: tdata = {Q, I}, each s16, 256 kS/s.   y[n] = sat(round(sum_k h[k] x[n-k] >> 17)), x[<0] = 0.
// Same arithmetic as the comp FIR (s18 taps, exact accumulator, rounded and saturated to s16), so this reuses
// ddc_comp_fir with the RRC taps rather than a second FIR. 62 cycles per sample of the ~390 a 100 MHz clock has per
// 256 kS/s sample: 6.3x real time (data/results/rrc_rtl_sim.csv). Folding symmetric taps through the DSP pre-adder
// would halve that; not needed while the Viterbi (~14x) is not the limit either.
module sync_rrc #(
    parameter int    W        = 16,  // fixed-point.md §RRC
    parameter int    NTAPS    = 57,  // ±8 symbols at 3.56 sps; rrc_fixed.taps(RxConfig()).size
    parameter string TAP_FILE = "rrc_taps.mem"  // written by scripts/gen_rtl_tables.py from rrc_fixed.taps()
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

    ddc_comp_fir #(
        .W         (W),
        .NTAPS     (NTAPS),
        .COEF_W    (18),  // s1.17, DSP48E1 B port; fixed-point.md §RRC
        .COEF_FRAC (17),  // rrc_fixed.RRC_FRAC
        .ACC_W     (40),  // >= W + COEF_W + log2(NTAPS) = 39.8; fixed-point.md §RRC
        .TAP_FILE  (TAP_FILE)
    ) u_fir (
        .clk_i      (clk_i),
        .rst_i      (rst_i),
        .s_tdata_i  (s_tdata_i),
        .s_tvalid_i (s_tvalid_i),
        .s_tready_o (s_tready_o),
        .m_tdata_o  (m_tdata_o),
        .m_tvalid_o (m_tvalid_o),
        .m_tready_i (m_tready_i)
    );

endmodule

`default_nettype wire
