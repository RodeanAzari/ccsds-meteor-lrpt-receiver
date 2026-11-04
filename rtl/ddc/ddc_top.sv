`default_nettype none

// DDC: cu8 I/Q at 1.024 MS/s -> s16 baseband I/Q at 256 kS/s (Phase B; CLAUDE.md §3.3; docs/fixed-point.md §DDC;
// bit-true model: model/ddc_fixed.py ddc_fixed_rails()).
//
//   ddc_ingest (cu8 -> s9, DC block -> s10) -> ddc_nco_mixer (-> s16) -> ddc_cic (/4) -> ddc_comp_fir (-> s16)
//
// In:  s_tdata = {Q_u8, I_u8}.   Out: m_tdata = {Q, I}, each s16.   freq_word_i: NCO tuning word, f / fs * 2^32.
// Every stage honours backpressure; a stall at the output propagates back to s_tready.
module ddc_top #(
    parameter string NCO_LUT_FILE  = "nco_lut.mem",       // scripts/gen_rtl_tables.py
    parameter string COMP_TAP_FILE = "comp_fir_taps.mem"  // scripts/gen_rtl_tables.py
) (
    input  wire logic        clk_i,
    input  wire logic        rst_i,
    input  wire logic [31:0] freq_word_i,

    input  wire logic [15:0] s_tdata_i,
    input  wire logic        s_tvalid_i,
    output      logic        s_tready_o,

    output      logic [31:0] m_tdata_o,
    output      logic        m_tvalid_o,
    input  wire logic        m_tready_i
);

    logic [19:0] dc_tdata;
    logic        dc_tvalid, dc_tready;
    logic [31:0] mix_tdata;
    logic        mix_tvalid, mix_tready;
    logic [31:0] cic_tdata;
    logic        cic_tvalid, cic_tready;

    ddc_ingest u_ingest (
        .clk_i      (clk_i),
        .rst_i      (rst_i),
        .s_tdata_i  (s_tdata_i),
        .s_tvalid_i (s_tvalid_i),
        .s_tready_o (s_tready_o),
        .m_tdata_o  (dc_tdata),
        .m_tvalid_o (dc_tvalid),
        .m_tready_i (dc_tready)
    );

    ddc_nco_mixer #(
        .LUT_FILE (NCO_LUT_FILE)
    ) u_mixer (
        .clk_i       (clk_i),
        .rst_i       (rst_i),
        .freq_word_i (freq_word_i),
        .s_tdata_i   (dc_tdata),
        .s_tvalid_i  (dc_tvalid),
        .s_tready_o  (dc_tready),
        .m_tdata_o   (mix_tdata),
        .m_tvalid_o  (mix_tvalid),
        .m_tready_i  (mix_tready)
    );

    ddc_cic u_cic (
        .clk_i      (clk_i),
        .rst_i      (rst_i),
        .s_tdata_i  (mix_tdata),
        .s_tvalid_i (mix_tvalid),
        .s_tready_o (mix_tready),
        .m_tdata_o  (cic_tdata),
        .m_tvalid_o (cic_tvalid),
        .m_tready_i (cic_tready)
    );

    ddc_comp_fir #(
        .TAP_FILE (COMP_TAP_FILE)
    ) u_fir (
        .clk_i      (clk_i),
        .rst_i      (rst_i),
        .s_tdata_i  (cic_tdata),
        .s_tvalid_i (cic_tvalid),
        .s_tready_o (cic_tready),
        .m_tdata_o  (m_tdata_o),
        .m_tvalid_o (m_tvalid_o),
        .m_tready_i (m_tready_i)
    );

endmodule

`default_nettype wire
