`default_nettype none

// Frame sync: 4-bit soft symbols in, derotated per-frame Viterbi windows out (buildplan §3.5, ADR 0010; bit-true
// model: model/framesync_fixed.py frame_sync_fixed() then windows()).
//
//   s (u, one symbol per beat) -+-> fec_fs_correlator -> fec_fs_fsm -> descriptors -+
//                               +-> fec_fs_window (ring) <--------------------------+--> m (fec_viterbi input)
//
// In:  s_tdata = u, 4-bit quantized soft symbol (fec_soft_quant).   Out: see fec_fs_window: m_tdata = {b, a},
// m_tuser = {flywheel, swap, alternate}, m_tlast = window end. Everything on the input side advances on the input
// handshake, so the correlator, FSM and ring stay aligned however the stream stalls.
module fec_framesync #(
    parameter int    SOFT_BITS     = 4,                  // ADR 0005
    parameter int    FRAME         = 16384,              // model/coding.py CODED_FRAME_SYMBOLS
    parameter int    ASM_TRANSIENT = 12,                 // model/coding.py ASM_TRANSIENT_SYMBOLS
    parameter int    PATTERN_LEN   = 52,                 // 64 encoded ASM symbols less ASM_TRANSIENT
    parameter int    PRE           = 128,                // framesync_fixed.PRE_SYMBOLS
    parameter int    POST          = 192,                // framesync_fixed.POST_SYMBOLS
    parameter int    DEPTH         = 32768,              // ring, symbols (4 RAMB36 at 4 bits)
    parameter int    COUNT_BITS    = 16,
    parameter string PATTERN_FILE  = "asm_patterns.mem"  // scripts/gen_rtl_tables.py
) (
    input  wire logic                   clk_i,
    input  wire logic                   rst_i,
    input  wire logic [5:0]             thr64_i,     // control register: 48 (RxConfig.sync_threshold 0.75 * 64)
    input  wire logic [3:0]             flywheel_i,  // control register: 4 (RxConfig.flywheel)

    input  wire logic [SOFT_BITS-1:0]   s_tdata_i,
    input  wire logic                   s_tvalid_i,
    output      logic                   s_tready_o,

    output      logic [2*SOFT_BITS-1:0] m_tdata_o,
    output      logic [2:0]             m_tuser_o,
    output      logic                   m_tlast_o,
    output      logic                   m_tvalid_o,
    input  wire logic                   m_tready_i,

    output      logic                   locked_o,
    output      logic [COUNT_BITS-1:0]  dropped_o,
    output      logic [COUNT_BITS-1:0]  slips_o,
    output      logic [COUNT_BITS-1:0]  early_o
);

    localparam int HYPS     = 4;   // receiver._hypothesis_patterns()
    localparam int POS_BITS = 32;  // positions wrap after 2^32 symbols (8 h); only differences and equality are used
    localparam int LAG      = PATTERN_LEN + 1;  // beats before hit is valid: the window, plus the compare stage
    localparam int WARM_W   = $clog2(LAG + 1);

    logic            beat;
    logic [HYPS-1:0] hit;
    logic [WARM_W-1:0] warm_q;  // beats so far, up to LAG

    assign beat = s_tvalid_i && s_tready_o;

    always_ff @(posedge clk_i) begin
        if (rst_i)                                         warm_q <= '0;
        else if (beat && warm_q != WARM_W'(LAG))          warm_q <= warm_q + 1'b1;
    end

    fec_fs_correlator #(
        .SOFT_BITS    (SOFT_BITS),
        .PATTERN_LEN  (PATTERN_LEN),
        .HYPS         (HYPS),
        .THR_BITS     (6),
        .PATTERN_FILE (PATTERN_FILE)
    ) u_corr (
        .clk_i   (clk_i),
        .rst_i   (rst_i),
        .en_i    (beat),
        .u_i     (s_tdata_i),
        .thr64_i (thr64_i),
        .hit_o   (hit)
    );

    logic                    d_valid [2];
    logic [POS_BITS-1:0]     d_first [2];
    logic [$clog2(HYPS)-1:0] d_hyp   [2];
    logic                    d_fly   [2];

    // On the beat that writes symbol t >= LAG, hit is for position t - LAG (fec_fs_correlator).
    fec_fs_fsm #(
        .FRAME         (FRAME),
        .ASM_TRANSIENT (ASM_TRANSIENT),
        .PRE           (PRE),
        .CANDIDATES    (4),  // framesync_fixed.CANDIDATES
        .HYPS          (HYPS),
        .POS_BITS      (POS_BITS),
        .COUNT_BITS    (COUNT_BITS)
    ) u_fsm (
        .clk_i      (clk_i),
        .rst_i      (rst_i),
        .en_i       (beat && warm_q == WARM_W'(LAG)),
        .hit_i      (hit),
        .flywheel_i (flywheel_i),
        .d_valid_o  (d_valid),
        .d_first_o  (d_first),
        .d_hyp_o    (d_hyp),
        .d_fly_o    (d_fly),
        .locked_o   (locked_o),
        .dropped_o  (dropped_o),
        .slips_o    (slips_o),
        .early_o    (early_o)
    );

    fec_fs_window #(
        .SOFT_BITS (SOFT_BITS),
        .FRAME     (FRAME),
        .PRE       (PRE),
        .POST      (POST),
        .DEPTH     (DEPTH),
        .DESC      (4),
        .POS_BITS  (POS_BITS),
        .HYPS      (HYPS)
    ) u_win (
        .clk_i      (clk_i),
        .rst_i      (rst_i),
        .s_tdata_i  (s_tdata_i),
        .s_tvalid_i (s_tvalid_i),
        .s_tready_o (s_tready_o),
        .d_valid_i  (d_valid),
        .d_first_i  (d_first),
        .d_hyp_i    (d_hyp),
        .d_fly_i    (d_fly),
        .m_tdata_o  (m_tdata_o),
        .m_tuser_o  (m_tuser_o),
        .m_tlast_o  (m_tlast_o),
        .m_tvalid_o (m_tvalid_o),
        .m_tready_i (m_tready_i)
    );

endmodule

`default_nettype wire
