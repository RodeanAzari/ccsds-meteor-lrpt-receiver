`default_nettype none

// Fully parallel 64-state Viterbi ACS, one trellis step per clock (CLAUDE.md §3.6; ADRs 0005, 0006; bit-true
// model: model/viterbi_fixed.py acs()).
//
// In:  s_tdata = {b, a}, the step's two quantized soft symbols (G1 then G2, SOFT_BITS each, viterbi_fixed.quantize()).
// Out: m_tdata = the step's 64 decision bits, bit s = 1 when state s's survivor comes from predecessor 1. These are
//      the rows the traceback stores (ADR 0007).
// Trellis (model/coding.py _trellis()): state s holds the last 6 input bits, newest in the LSB. Predecessor j of s
// is {j, s[5:1]}; the 7-bit register on that branch is {j, s}, and the coded bits are the parities of its G1 and G2
// taps. The path metrics start at zero, as in the model, and wrap modulo 2^PM_BITS (no normalization).
module fec_acs_array #(
    parameter int         SOFT_BITS = 4,            // ADR 0005
    parameter int         PM_BITS   = 9,            // ADR 0006: viterbi_fixed.path_metric_bits(4)
    parameter logic [6:0] G1_TAPS   = 7'b1001111,   // signal-spec.md: G1 = 171 octal, coding.py _G1_TAPS (0,1,2,3,6)
    parameter logic [6:0] G2_TAPS   = 7'b1101101    // signal-spec.md: G2 = 133 octal, coding.py _G2_TAPS (0,2,3,5,6)
) (
    input  wire logic                   clk_i,
    input  wire logic                   rst_i,

    input  wire logic [2*SOFT_BITS-1:0] s_tdata_i,
    input  wire logic                   s_tvalid_i,
    output      logic                   s_tready_o,

    output      logic [63:0]            m_tdata_o,
    output      logic                   m_tvalid_o,
    input  wire logic                   m_tready_i
);

    localparam int N_STATES = 64;  // 2^(K-1), K = 7 (signal-spec.md)

    logic [3:0][SOFT_BITS:0] bm;
    logic [PM_BITS-1:0]   pm_q [N_STATES];
    logic [PM_BITS-1:0]   pm_d [N_STATES];
    logic [N_STATES-1:0]  dec_d;

    fec_bm #(
        .SOFT_BITS (SOFT_BITS)
    ) u_bm (
        .a_i  (s_tdata_i[SOFT_BITS-1:0]),
        .b_i  (s_tdata_i[2*SOFT_BITS-1:SOFT_BITS]),
        .bm_o (bm)
    );

    for (genvar s = 0; s < N_STATES; s++) begin : g_state
        localparam logic [6:0] REG0 = {1'b0, 6'(s)};  // branch register from predecessor 0
        localparam logic [6:0] REG1 = {1'b1, 6'(s)};
        localparam logic [1:0] BM0 = {1'(^(REG0 & G1_TAPS)), 1'(^(REG0 & G2_TAPS))};
        localparam logic [1:0] BM1 = {1'(^(REG1 & G1_TAPS)), 1'(^(REG1 & G2_TAPS))};

        fec_acs #(
            .PM_BITS (PM_BITS),
            .BM_BITS (SOFT_BITS + 1)
        ) u_acs (
            .pm0_i (pm_q[s >> 1]),
            .pm1_i (pm_q[(s >> 1) | 32]),
            .bm0_i (bm[BM0]),
            .bm1_i (bm[BM1]),
            .pm_o  (pm_d[s]),
            .dec_o (dec_d[s])
        );
    end

    assign s_tready_o = !m_tvalid_o || m_tready_i;

    always_ff @(posedge clk_i) begin
        if (rst_i) begin
            m_tvalid_o <= 1'b0;
            for (int s = 0; s < N_STATES; s++) pm_q[s] <= '0;
        end else if (s_tvalid_i && s_tready_o) begin
            m_tvalid_o <= 1'b1;
            pm_q       <= pm_d;
        end else if (m_tready_i) begin
            m_tvalid_o <= 1'b0;
        end
    end

    always_ff @(posedge clk_i) begin
        if (s_tvalid_i && s_tready_o) m_tdata_o <= dec_d;
    end

`ifndef SYNTHESIS
    // ADR 0006 bound: any two path metrics differ by at most SPREAD = (K - 1) * BM_MAX (every state is reachable from
    // the best state K - 1 steps back). Any two ACS candidates then differ by at most SPREAD + BM_MAX, which a_width
    // keeps below 2^(PM_BITS-1), so every modulo compare picks what an unbounded compare would.
    // a_spread checks all 2,016 pairs at once: with each metric taken relative to state 0 as a PM_BITS-bit signed
    // value, max - min <= SPREAD. That is the same condition, since pairs within SPREAD < 2^(PM_BITS-1) don't wrap, and
    // a violation shows before anything can wrap (the spread grows by at most BM_MAX per step).
    // tb/formal/fec_acs_array.sby: a_hold proven; a_spread holds 8 steps from reset; its unbounded proof is open.
    localparam int BM_MAX = 2 * ((1 << SOFT_BITS) - 1);  // viterbi_fixed.max_branch_metric()
    localparam int SPREAD = 6 * BM_MAX;                   // K - 1 = 6 (signal-spec.md)

    int rel_max, rel_min;

    always_comb begin
        rel_max = 0;
        rel_min = 0;
        for (int s = 1; s < N_STATES; s++) begin
            if (int'($signed(pm_q[s] - pm_q[0])) > rel_max) rel_max = int'($signed(pm_q[s] - pm_q[0]));
            if (int'($signed(pm_q[s] - pm_q[0])) < rel_min) rel_min = int'($signed(pm_q[s] - pm_q[0]));
        end
    end

    always_ff @(posedge clk_i) begin
        a_width: assert (SPREAD + BM_MAX < (1 << (PM_BITS - 1)));
`ifndef ACS_HOLD_ONLY  // fec_acs_array.sby task hold proves a_hold alone
        if (!rst_i) a_spread: assert (rel_max - rel_min <= SPREAD);
`endif
    end

    // A metric changes only on an input handshake, so stalls add no metric values: the spread checks may step every
    // clock (fec_acs_array.sby, tasks bmc4/step and hold).
    for (genvar s = 0; s < N_STATES; s++) begin : g_hold
        always_ff @(posedge clk_i) begin
            if (!rst_i && $past(!rst_i) && !$past(s_tvalid_i && s_tready_o)) assert (pm_q[s] == $past(pm_q[s]));
        end
    end
`endif

endmodule

`default_nettype wire
