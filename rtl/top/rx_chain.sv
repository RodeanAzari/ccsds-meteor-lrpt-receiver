`default_nettype none

// Receiver chain after the DDC: soft samples -> CADUs (Phases D, E; bit-true model: sync_chain.expected() ->
// sync_fixed.serial() -> viterbi_fixed.quantize() -> framesync_fixed.frame_sync_fixed() -> windows() ->
// decode_windows() -> cadu_fixed.cadus_from_windows()).
//
//   sync_top -> fec_soft_quant -> fec_framesync -> fec_viterbi -> fec_frame_extract -> fec_cadu
//                                              \-- window flags (tap) --^
//
// In:  s_tdata = {Q, I}, each s16 (ddc_top output).   Out: CADUs, one byte per beat, m_tlast on byte 1,023,
// m_tuser = the CADU's status (fec_cadu; model/cadu_fixed.py CaduOut.status_word()). Every stage honours
// backpressure: the Viterbi (~96 clocks per bit) stalls the ring, which stalls the input; fec_cadu stalls the
// Viterbi while it runs RS and sends a CADU.
module rx_chain #(
    parameter string RRC_TAP_FILE = "rrc_taps.mem",      // scripts/gen_rtl_tables.py
    parameter string NCO_LUT_FILE = "nco_lut.mem",       // scripts/gen_rtl_tables.py
    parameter string PATTERN_FILE = "asm_patterns.mem",  // scripts/gen_rtl_tables.py
    parameter int    SOFT_BITS    = 4,                   // ADR 0005
    parameter int    COUNT_BITS   = 16                   // fec_framesync
) (
    input  wire logic                  clk_i,
    input  wire logic                  rst_i,
    input  wire logic [15:0]           costas_kp_i,       // sync_fixed.LoopGains.costas_kp
    input  wire logic [23:0]           costas_ki_i,       // .costas_ki
    input  wire logic [46:0]           costas_fmax_i,     // .costas_max
    input  wire logic [27:0]           timing_nominal_i,  // .timing_nominal
    input  wire logic [15:0]           timing_kp_i,       // .timing_kp
    input  wire logic [23:0]           timing_ki_i,       // .timing_ki
    input  wire logic [39:0]           timing_limit_i,    // .timing_limit
    input  wire logic [5:0]            thr64_i,           // control register: 48 (RxConfig.sync_threshold * 64)
    input  wire logic [3:0]            flywheel_i,        // control register: 4 (RxConfig.flywheel)
    input  wire logic [7:0]            depth_i,           // control register, ADR 0008: 96

    input  wire logic [31:0]           s_tdata_i,
    input  wire logic                  s_tvalid_i,
    output      logic                  s_tready_o,

    output      logic [7:0]            m_tdata_o,
    output      logic [32:0]           m_tuser_o,
    output      logic                  m_tlast_o,
    output      logic                  m_tvalid_o,
    input  wire logic                  m_tready_i,

    output      logic                  locked_o,
    output      logic [COUNT_BITS-1:0] dropped_o,
    output      logic [COUNT_BITS-1:0] slips_o,
    output      logic [COUNT_BITS-1:0] early_o,
    output      logic [COUNT_BITS-1:0] flag_ovf_o,  // fec_frame_extract: 0 in operation
    output      logic [COUNT_BITS-1:0] len_err_o    // fec_cadu: 0 in operation
);

    logic [31:0]            sync_tdata;
    logic                   sync_tvalid, sync_tready;
    logic [SOFT_BITS-1:0]   quant_tdata;
    logic                   quant_tvalid, quant_tready;
    logic [2*SOFT_BITS-1:0] win_tdata;
    logic                   win_tvalid, win_tready;
    logic [2:0]             win_tuser;
    logic                   win_tlast;
    logic                   dec_tdata, dec_tvalid, dec_tready;
    logic                   fr_tdata, fr_tlast, fr_tvalid, fr_tready;
    logic [2:0]             fr_tuser;

    sync_top #(
        .RRC_TAP_FILE (RRC_TAP_FILE),
        .NCO_LUT_FILE (NCO_LUT_FILE)
    ) u_sync (
        .clk_i            (clk_i),
        .rst_i            (rst_i),
        .costas_kp_i      (costas_kp_i),
        .costas_ki_i      (costas_ki_i),
        .costas_fmax_i    (costas_fmax_i),
        .timing_nominal_i (timing_nominal_i),
        .timing_kp_i      (timing_kp_i),
        .timing_ki_i      (timing_ki_i),
        .timing_limit_i   (timing_limit_i),
        .s_tdata_i        (s_tdata_i),
        .s_tvalid_i       (s_tvalid_i),
        .s_tready_o       (s_tready_o),
        .m_tdata_o        (sync_tdata),
        .m_tvalid_o       (sync_tvalid),
        .m_tready_i       (sync_tready)
    );

    fec_soft_quant #(
        .SOFT_BITS (SOFT_BITS)
    ) u_quant (
        .clk_i      (clk_i),
        .rst_i      (rst_i),
        .s_tdata_i  (sync_tdata),
        .s_tvalid_i (sync_tvalid),
        .s_tready_o (sync_tready),
        .m_tdata_o  (quant_tdata),
        .m_tvalid_o (quant_tvalid),
        .m_tready_i (quant_tready)
    );

    fec_framesync #(
        .SOFT_BITS    (SOFT_BITS),
        .COUNT_BITS   (COUNT_BITS),
        .PATTERN_FILE (PATTERN_FILE)
    ) u_framesync (
        .clk_i      (clk_i),
        .rst_i      (rst_i),
        .thr64_i    (thr64_i),
        .flywheel_i (flywheel_i),
        .s_tdata_i  (quant_tdata),
        .s_tvalid_i (quant_tvalid),
        .s_tready_o (quant_tready),
        .m_tdata_o  (win_tdata),
        .m_tuser_o  (win_tuser),
        .m_tlast_o  (win_tlast),
        .m_tvalid_o (win_tvalid),
        .m_tready_i (win_tready),
        .locked_o   (locked_o),
        .dropped_o  (dropped_o),
        .slips_o    (slips_o),
        .early_o    (early_o)
    );

    fec_viterbi #(
        .SOFT_BITS (SOFT_BITS)
    ) u_viterbi (
        .clk_i      (clk_i),
        .rst_i      (rst_i),
        .depth_i    (depth_i),
        .s_tdata_i  (win_tdata),
        .s_tvalid_i (win_tvalid),
        .s_tready_o (win_tready),
        .m_tdata_o  (dec_tdata),
        .m_tvalid_o (dec_tvalid),
        .m_tready_i (dec_tready)
    );

    fec_frame_extract #(
        .COUNT_BITS (COUNT_BITS)
    ) u_extract (
        .clk_i       (clk_i),
        .rst_i       (rst_i),
        .win_hs_i    (win_tvalid && win_tready),
        .win_last_i  (win_tlast),
        .win_tuser_i (win_tuser),
        .s_tdata_i   (dec_tdata),
        .s_tvalid_i  (dec_tvalid),
        .s_tready_o  (dec_tready),
        .m_tdata_o   (fr_tdata),
        .m_tuser_o   (fr_tuser),
        .m_tlast_o   (fr_tlast),
        .m_tvalid_o  (fr_tvalid),
        .m_tready_i  (fr_tready),
        .flag_ovf_o  (flag_ovf_o)
    );

    fec_cadu #(
        .COUNT_BITS (COUNT_BITS)
    ) u_cadu (
        .clk_i      (clk_i),
        .rst_i      (rst_i),
        .s_tdata_i  (fr_tdata),
        .s_tuser_i  (fr_tuser),
        .s_tlast_i  (fr_tlast),
        .s_tvalid_i (fr_tvalid),
        .s_tready_o (fr_tready),
        .m_tdata_o  (m_tdata_o),
        .m_tuser_o  (m_tuser_o),
        .m_tlast_o  (m_tlast_o),
        .m_tvalid_o (m_tvalid_o),
        .m_tready_i (m_tready_i),
        .len_err_o  (len_err_o)
    );

endmodule

`default_nettype wire
