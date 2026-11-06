`default_nettype none

// Viterbi decoder, K = 7, r = 1/2 (CLAUDE.md §3.6; bit-true model: model/viterbi_fixed.py viterbi_fixed() with
// depth = depth_i, start "zero"; ADRs 0005-0008).
//
//   fec_acs_array (64 states, one step per clock) -> fec_traceback (BRAM ring, depth_i + 3 clocks per bit)
//
// In:  s_tdata = {b, a}: one trellis step's quantized soft symbols, G1 then G2 (viterbi_fixed.quantize(), 4 bits,
//      step ONE/4). Pairing the symbols and resolving the phase is frame sync's job (buildplan §3.5), upstream.
// Out: m_tdata = decoded bits, one per step, delayed by depth_i steps; the first depth_i steps produce none.
module fec_viterbi #(
    parameter int SOFT_BITS = 4,   // ADR 0005
    parameter int PM_BITS   = 9,   // ADR 0006
    parameter int ROWS      = 256  // fec_traceback
) (
    input  wire logic                    clk_i,
    input  wire logic                    rst_i,
    input  wire logic [$clog2(ROWS)-1:0] depth_i,  // control register, ADR 0008: 96

    input  wire logic [2*SOFT_BITS-1:0]  s_tdata_i,
    input  wire logic                    s_tvalid_i,
    output      logic                    s_tready_o,

    output      logic                    m_tdata_o,
    output      logic                    m_tvalid_o,
    input  wire logic                    m_tready_i
);

    logic [63:0] dec_tdata;
    logic        dec_tvalid, dec_tready;

    fec_acs_array #(
        .SOFT_BITS (SOFT_BITS),
        .PM_BITS   (PM_BITS)
    ) u_acs (
        .clk_i      (clk_i),
        .rst_i      (rst_i),
        .s_tdata_i  (s_tdata_i),
        .s_tvalid_i (s_tvalid_i),
        .s_tready_o (s_tready_o),
        .m_tdata_o  (dec_tdata),
        .m_tvalid_o (dec_tvalid),
        .m_tready_i (dec_tready)
    );

    fec_traceback #(
        .ROWS (ROWS)
    ) u_tb (
        .clk_i      (clk_i),
        .rst_i      (rst_i),
        .depth_i    (depth_i),
        .s_tdata_i  (dec_tdata),
        .s_tvalid_i (dec_tvalid),
        .s_tready_o (dec_tready),
        .m_tdata_o  (m_tdata_o),
        .m_tvalid_o (m_tvalid_o),
        .m_tready_i (m_tready_i)
    );

endmodule

`default_nettype wire
