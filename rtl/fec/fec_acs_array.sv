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
    // tb/formal/fec_acs_array.sby: a_hold proven; a_spread proven in every reachable state (ACS_GHOST below).
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

`ifdef ACS_GHOST
    // Invariant groups of the ghost proof below; G_N selects the task that derives a_spread from them.
    localparam int G_E = 0, G_B = 1, G_N = 7;  // G_B + j - 1: band B at level j = 1..6
    localparam int G_L = G_N, G_S = G_N + 1;   // tasks that derive lemma L, then a_spread from L
    localparam bit CHECK_SPREAD = (`GHOST_SEL == G_S);
`else
    localparam bit CHECK_SPREAD = 1'b1;
`endif

    always_ff @(posedge clk_i) begin
        a_width: assert (SPREAD + BM_MAX < (1 << (PM_BITS - 1)));
`ifndef ACS_HOLD_ONLY  // fec_acs_array.sby task hold proves a_hold alone
        if (!rst_i && CHECK_SPREAD) a_spread: assert (rel_max - rel_min <= SPREAD);
`endif
    end

`ifdef ACS_GHOST
    // Unbounded proof of a_spread (tb/formal/fec_acs_array.sby, tasks ghost_*; docs/viterbi.md). The bound is the
    // reachability argument of ADR 0006, made 1-step inductive with ghost state:
    //   g_m[s]  the metrics again, GW bits wide, so every compare below is exact (no PM_BITS wrap);
    //   U_j[v]  for j = 1..6: the min of g_m, j steps ago, over the states that reach a state s with s >> j == v in
    //           exactly j steps (those u with u[5-j:0] == s[5:j]), plus j * BM_MAX. Updated as BM_MAX plus the min of
    //           the two level-(j-1) entries those states split into (the two predecessors' cosets).
    // Invariants (each follows from all of them one step earlier, per state and level):
    //   E    pm_q[s] == g_m[s] mod 2^PM_BITS                       (the RTL's modulo compare picks the exact min)
    //   B_j  0 <= U_j[s >> j] - g_m[s] <= j * BM_MAX               (a metric is at least its ancestors' best, as
    //                                                               branch metrics are >= 0, and at most that plus
    //                                                               j steps' worth)
    // At j = 6 the coset is every state: all metrics lie in [U_6 - SPREAD, U_6], which is a_spread. B also keeps every
    // ghost value within 2 * SPREAD of U_6, far inside 2^(GW-1), so the GW-bit compares never wrap.
    // One query over a heavier invariant set did not finish in 9 hours, so each sby task checks one group
    // (GHOST_SEL = G_E, G_B .. G_B + 5): it asserts that group and assumes every group held one step earlier
    // (g_ok_prev_q). All groups hold after reset and each holds whenever all held a step before, so all hold in every
    // reachable state. a_spread then follows in two steps, each a task that assumes everything before it now:
    //   L  every rel(s) = pm_q[s] - pm_q[0] (as a_spread takes it) lies in [lo, lo + SPREAD], lo = U_6 - SPREAD - g_m[0]
    //      (E, and B_6 puts every g_m[s] in [U_6 - SPREAD, U_6]; one query from E and B straight to a_spread's max/min
    //      chains did not finish in 2 hours);
    //   a_spread  every element of its max/min chains lies in one window of width SPREAD.
    localparam int GW = 12;  // ghost width: compared values are within 2 * SPREAD + BM_MAX of each other, < 2^(GW-1)

    // Verilog-2001 function style: Yosys's own parser takes no `return`.
    function automatic integer u_base(input integer j);  // level j's U entries: g_u_q[u_base(j) +: 2^(6-j)]
        u_base = N_STATES - (1 << (7 - j));
    endfunction

    function automatic [GW-1:0] gmin(input [GW-1:0] a, input [GW-1:0] b);
        gmin = ($signed(b - a) < 0) ? b : a;
    endfunction

    logic [N_STATES*GW-1:0] g_m_q, g_m_d;
    logic [63*GW-1:0]       g_u_q, g_u_d;  // 32 + 16 + 8 + 4 + 2 + 1 entries
    logic [G_N-1:0]         g_ok, g_ok_prev_q;
    logic                   g_lemma_ok;
    int                     g_lo;

    for (genvar s = 0; s < N_STATES; s++) begin : g_ghost_m
        localparam logic [6:0] GREG0 = {1'b0, 6'(s)};
        localparam logic [6:0] GREG1 = {1'b1, 6'(s)};
        localparam logic [1:0] GBM0 = {1'(^(GREG0 & G1_TAPS)), 1'(^(GREG0 & G2_TAPS))};
        localparam logic [1:0] GBM1 = {1'(^(GREG1 & G1_TAPS)), 1'(^(GREG1 & G2_TAPS))};
        assign g_m_d[s*GW +: GW] = gmin(g_m_q[(s >> 1)*GW +: GW] + GW'(bm[GBM0]),
                                        g_m_q[((s >> 1) | 32)*GW +: GW] + GW'(bm[GBM1]));
    end

    for (genvar j = 1; j <= 6; j++) begin : g_ghost_u
        for (genvar v = 0; v < (1 << (6 - j)); v++) begin : g_v
            if (j == 1) begin : g_from_m
                assign g_u_d[(u_base(1) + v)*GW +: GW] = gmin(g_m_q[v*GW +: GW], g_m_q[(v | 32)*GW +: GW])
                                                         + GW'(BM_MAX);
            end else begin : g_from_u
                assign g_u_d[(u_base(j) + v)*GW +: GW] =
                    gmin(g_u_q[(u_base(j - 1) + v)*GW +: GW],
                         g_u_q[(u_base(j - 1) + ((1 << (6 - j)) | v))*GW +: GW]) + GW'(BM_MAX);
            end
        end
    end

    always_ff @(posedge clk_i) begin
        if (rst_i) begin
            g_m_q <= '0;
            for (int j = 1; j <= 6; j++)
                for (int v = 0; v < (1 << (6 - j)); v++) g_u_q[(u_base(j) + v)*GW +: GW] <= GW'(j * BM_MAX);
        end else if (s_tvalid_i && s_tready_o) begin
            g_m_q <= g_m_d;
            g_u_q <= g_u_d;
        end
    end

    // Each group's invariants, on the current state.
    always_comb begin
        g_ok = '1;
        for (int s = 0; s < N_STATES; s++) begin
            if (pm_q[s] != g_m_q[s*GW +: PM_BITS]) g_ok[G_E] = 1'b0;
            for (int j = 1; j <= 6; j++)
                if ($signed(g_u_q[(u_base(j) + (s >> j))*GW +: GW] - g_m_q[s*GW +: GW]) < 0
                    || $signed(g_u_q[(u_base(j) + (s >> j))*GW +: GW] - g_m_q[s*GW +: GW]) > j * BM_MAX)
                    g_ok[G_B + j - 1] = 1'b0;
        end
    end

    always_ff @(posedge clk_i) g_ok_prev_q <= g_ok | {G_N{rst_i}};  // a reset makes every group hold next

    always_comb begin
        g_lo = int'($signed(g_u_q[u_base(6)*GW +: GW] - GW'(SPREAD) - g_m_q[0 +: GW]));
        g_lemma_ok = 1'b1;
        for (int s = 0; s < N_STATES; s++)
            if (int'($signed(pm_q[s] - pm_q[0])) < g_lo || int'($signed(pm_q[s] - pm_q[0])) > g_lo + SPREAD)
                g_lemma_ok = 1'b0;
    end

    always_comb begin
        if (!rst_i) begin
            for (int k = 0; k < G_N; k++) begin
                if (k == `GHOST_SEL)       assert (g_ok[k]);
                else if (`GHOST_SEL >= G_N) assume (g_ok[k]);
                else                        assume (g_ok_prev_q[k]);
            end
            if (`GHOST_SEL == G_L) assert (g_lemma_ok);
            if (`GHOST_SEL == G_S) assume (g_lemma_ok);
        end
    end
`endif

    // A metric changes only on an input handshake, so stalls add no metric values: the spread checks may step every
    // clock (fec_acs_array.sby, tasks bmc4/step and hold). Task hold proves it; the ghost tasks leave it out.
`ifndef ACS_GHOST
    for (genvar s = 0; s < N_STATES; s++) begin : g_hold
        always_ff @(posedge clk_i) begin
            if (!rst_i && $past(!rst_i) && !$past(s_tvalid_i && s_tready_o)) assert (pm_q[s] == $past(pm_q[s]));
        end
    end
`endif
`endif

endmodule

`default_nettype wire
