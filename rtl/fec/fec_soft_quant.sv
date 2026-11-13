`default_nettype none

// Serial soft stream and 4-bit quantizer between the sync chain and frame sync (bit-true model:
// model/sync_fixed.py serial(), then model/viterbi_fixed.py quantize(soft, SOFT_BITS, SHIFT); ADR 0005).
//
// In:  s_tdata = {Q, I}, each s16, two per symbol (sync_top output). Beat k after reset contributes I if k is even,
//      Q if odd: re[0], im[1], re[2], ... (receiver.serial_soft()).
// Out: m_tdata = u = clamp((x >>> SHIFT) + 2^(SOFT_BITS-1), 0, 2^SOFT_BITS - 1), one per input beat.
// Pass-through handshake: no storage, so no beat can be dropped or repeated; the rail toggles on each handshake.
module fec_soft_quant #(
    parameter int IN_BITS   = 16,  // docs/fixed-point.md §Synchronization: s16 rails
    parameter int SOFT_BITS = 4,   // ADR 0005
    parameter int SHIFT     = 10   // ADR 0005: step ONE/4, ONE = 2^12
) (
    input  wire logic                 clk_i,
    input  wire logic                 rst_i,

    input  wire logic [2*IN_BITS-1:0] s_tdata_i,
    input  wire logic                 s_tvalid_i,
    output      logic                 s_tready_o,

    output      logic [SOFT_BITS-1:0] m_tdata_o,
    output      logic                 m_tvalid_o,
    input  wire logic                 m_tready_i
);

    localparam int SHIFTED = IN_BITS - SHIFT;  // width of x >>> SHIFT
    localparam int TOP     = (1 << SOFT_BITS) - 1;
    localparam int MID     = 1 << (SOFT_BITS - 1);

    logic                      odd_q;  // the next beat is an odd stream index: take Q
    logic signed [IN_BITS-1:0] x;
    logic signed [SHIFTED:0]   level;  // one bit wider: x >>> SHIFT plus MID cannot overflow

    assign s_tready_o = m_tready_i;
    assign m_tvalid_o = s_tvalid_i;

    always_comb begin
        x     = odd_q ? s_tdata_i[2*IN_BITS-1:IN_BITS] : s_tdata_i[IN_BITS-1:0];
        level = (SHIFTED + 1)'(x >>> SHIFT) + (SHIFTED + 1)'(MID);
        if (level < 0)                         m_tdata_o = '0;
        else if (level > (SHIFTED + 1)'(TOP))  m_tdata_o = SOFT_BITS'(TOP);
        else                                   m_tdata_o = level[SOFT_BITS-1:0];
    end

    always_ff @(posedge clk_i) begin
        if (rst_i)                          odd_q <= 1'b0;
        else if (s_tvalid_i && m_tready_i)  odd_q <= ~odd_q;
    end

`ifndef SYNTHESIS
    // Coverage bins (make cov, docs/coverage.md): backpressure on each interface.
    cov_bp_s: cover property (@(posedge clk_i) disable iff (rst_i) s_tvalid_i && !s_tready_o);
    cov_bp_m: cover property (@(posedge clk_i) disable iff (rst_i) m_tvalid_o && !m_tready_i);
`endif

endmodule

`default_nettype wire
