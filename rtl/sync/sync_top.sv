`default_nettype none

// Synchronization chain: DDC output -> soft samples at 2 per symbol (Phase C; ADR 0002; docs/fixed-point.md
// §Synchronization; bit-true model: model/sync_fixed.py, rrc_fixed -> agc -> costas -> timing).
//
//   sync_rrc (57-tap matched filter) -> sync_agc (rail rms -> ONE) -> sync_costas (carrier) -> sync_timing (2 sps)
//
// In:  s_tdata = {Q, I}, each s16, 256 kS/s (ddc_top output; the host's coarse estimate is already in the DDC NCO
// word, ADR 0002).   Out: m_tdata = {Q, I}, each s16, two per symbol (sync_fixed.timing()).
// The loop gains are control registers (CLAUDE.md §3.1), computed by sync_fixed.loop_gains(). Every stage honours
// backpressure; a stall at the output propagates back to s_tready.
module sync_top #(
    parameter string RRC_TAP_FILE = "rrc_taps.mem",  // scripts/gen_rtl_tables.py
    parameter string NCO_LUT_FILE = "nco_lut.mem"    // the DDC's table; scripts/gen_rtl_tables.py
) (
    input  wire logic        clk_i,
    input  wire logic        rst_i,
    input  wire logic [15:0] costas_kp_i,       // sync_fixed.LoopGains.costas_kp
    input  wire logic [23:0] costas_ki_i,       // .costas_ki
    input  wire logic [46:0] costas_fmax_i,     // .costas_max
    input  wire logic [27:0] timing_nominal_i,  // .timing_nominal
    input  wire logic [15:0] timing_kp_i,       // .timing_kp
    input  wire logic [23:0] timing_ki_i,       // .timing_ki
    input  wire logic [39:0] timing_limit_i,    // .timing_limit

    input  wire logic [31:0] s_tdata_i,
    input  wire logic        s_tvalid_i,
    output      logic        s_tready_o,

    output      logic [31:0] m_tdata_o,
    output      logic        m_tvalid_o,
    input  wire logic        m_tready_i
);

    logic [31:0] rrc_tdata;
    logic        rrc_tvalid, rrc_tready;
    logic [31:0] agc_tdata;
    logic        agc_tvalid, agc_tready;
    logic [31:0] cos_tdata;
    logic        cos_tvalid, cos_tready;

    sync_rrc #(
        .TAP_FILE (RRC_TAP_FILE)
    ) u_rrc (
        .clk_i      (clk_i),
        .rst_i      (rst_i),
        .s_tdata_i  (s_tdata_i),
        .s_tvalid_i (s_tvalid_i),
        .s_tready_o (s_tready_o),
        .m_tdata_o  (rrc_tdata),
        .m_tvalid_o (rrc_tvalid),
        .m_tready_i (rrc_tready)
    );

    sync_agc u_agc (
        .clk_i      (clk_i),
        .rst_i      (rst_i),
        .s_tdata_i  (rrc_tdata),
        .s_tvalid_i (rrc_tvalid),
        .s_tready_o (rrc_tready),
        .m_tdata_o  (agc_tdata),
        .m_tvalid_o (agc_tvalid),
        .m_tready_i (agc_tready)
    );

    sync_costas #(
        .LUT_FILE (NCO_LUT_FILE)
    ) u_costas (
        .clk_i      (clk_i),
        .rst_i      (rst_i),
        .kp_i       (costas_kp_i),
        .ki_i       (costas_ki_i),
        .fmax_i     (costas_fmax_i),
        .s_tdata_i  (agc_tdata),
        .s_tvalid_i (agc_tvalid),
        .s_tready_o (agc_tready),
        .m_tdata_o  (cos_tdata),
        .m_tvalid_o (cos_tvalid),
        .m_tready_i (cos_tready)
    );

    sync_timing u_timing (
        .clk_i      (clk_i),
        .rst_i      (rst_i),
        .nominal_i  (timing_nominal_i),
        .kp_i       (timing_kp_i),
        .ki_i       (timing_ki_i),
        .limit_i    (timing_limit_i),
        .s_tdata_i  (cos_tdata),
        .s_tvalid_i (cos_tvalid),
        .s_tready_o (cos_tready),
        .m_tdata_o  (m_tdata_o),
        .m_tvalid_o (m_tvalid_o),
        .m_tready_i (m_tready_i)
    );

endmodule

`default_nettype wire
