`default_nettype none

// Frame sync state machine: SEARCH -> VERIFY -> LOCK with a flywheel and slip following (buildplan §3.5, ADR 0010;
// bit-true model: model/framesync_fixed.py frame_sync_fixed(), which this matches frame for frame).
//
// One position per en_i: hit_i holds the 4 hypotheses' threshold hits for the correlation window starting at symbol
// pos (fec_fs_correlator), pos = 0 on the first en_i after reset.
//   SEARCH: a queued peak at p comes due at p + FRAME: if its hypothesis hits there too, lock and emit both frames
//           (the delay line still holds the first). Otherwise drop it, and queue any peak at pos (lowest hypothesis;
//           a full queue drops the peak and counts it).
//   LOCK:   the ASM expected at e is judged at pos = e + SLIP, from a history of the hits at e - SLIP .. e + SLIP:
//           the locked hypothesis at e, else any hypothesis nearest e (0, -1, +1, -2, +2; lowest hypothesis), which
//           is a slip, else a miss. More than flywheel_i misses in a row return to SEARCH. Otherwise the frame is
//           emitted, flagged if missed. A miss means no hit anywhere in e +- SLIP, so nothing at e + 1 .. e + SLIP
//           needed queuing and SEARCH resumes at the next position, as in the model.
// Emits up to two frame descriptors per position, oldest on port 0: first = the Viterbi window's first symbol, frame
// start - PRE (frame start = ASM position - ASM_TRANSIENT, its first coded symbol), hypothesis h = {swap, alternate}
// (receiver._hypothesis_patterns() order), flywheel flag.
// A frame whose Viterbi run-in would begin before symbol 0 (start < PRE) is not emitted; it is counted in early_o.
module fec_fs_fsm #(
    parameter int FRAME         = 16384,  // model/coding.py CODED_FRAME_SYMBOLS
    parameter int ASM_TRANSIENT = 12,     // model/coding.py ASM_TRANSIENT_SYMBOLS
    parameter int PRE           = 128,    // framesync_fixed.PRE_SYMBOLS
    parameter int CANDIDATES    = 4,      // framesync_fixed.CANDIDATES
    parameter int HYPS          = 4,      // receiver._hypothesis_patterns()
    parameter int POS_BITS      = 32,     // symbol positions wrap; only equality is ever tested
    parameter int COUNT_BITS    = 16      // status counters, saturating
) (
    input  wire logic                  clk_i,
    input  wire logic                  rst_i,
    input  wire logic                  en_i,
    input  wire logic [HYPS-1:0]       hit_i,
    input  wire logic [3:0]            flywheel_i,  // control register: RxConfig.flywheel = 4

    output      logic                  d_valid_o [2],
    output      logic [POS_BITS-1:0]   d_first_o [2],
    output      logic [$clog2(HYPS)-1:0] d_hyp_o [2],
    output      logic                  d_fly_o   [2],

    output      logic                  locked_o,
    output      logic [COUNT_BITS-1:0] dropped_o,  // peaks dropped: verify queue full
    output      logic [COUNT_BITS-1:0] slips_o,    // hypothesis/position switches in lock
    output      logic [COUNT_BITS-1:0] early_o     // frames not emitted: run-in before symbol 0
);

    localparam int SLIP = 2;  // framesync_fixed.SLIP_SYMBOLS; the history below holds e - 2 .. e + 2
    localparam int HW   = $clog2(HYPS);
    localparam int QW   = $clog2(CANDIDATES + 1);  // queue count 0 .. CANDIDATES
    localparam int QI   = $clog2(CANDIDATES);      // queue index; a push never indexes CANDIDATES (that is a drop)
    localparam logic [POS_BITS-1:0] WARM = POS_BITS'(PRE + ASM_TRANSIENT);  // first ASM position with a run-in

    function automatic logic [HW-1:0] lowest(input logic [HYPS-1:0] h);
        lowest = '0;
        for (int i = HYPS - 1; i >= 0; i--) if (h[i]) lowest = HW'(i);
    endfunction

    function automatic logic [COUNT_BITS-1:0] sat_inc(input logic [COUNT_BITS-1:0] c);
        return &c ? c : c + 1'b1;
    endfunction

    logic [POS_BITS-1:0] pos_q;
    logic                warm_q;                // pos has reached WARM
    logic [HYPS-1:0]     hist_q [SLIP * 2];     // hist_q[i] = hits at pos - 1 - i
    logic                locked_q;
    logic [POS_BITS-1:0] exp_q;                 // LOCK: expected ASM position
    logic [HW-1:0]       lhyp_q;
    logic [4:0]          misses_q;
    logic [QW-1:0]       qcount_q;
    logic [POS_BITS-1:0] qpos_q   [CANDIDATES];
    logic [HW-1:0]       qhyp_q   [CANDIDATES];
    logic                qearly_q [CANDIDATES];
    logic [COUNT_BITS-1:0] dropped_q, slips_q, early_q;

    // ---- decision for the current position (used only when en_i)
    logic            warm;
    logic [HYPS-1:0] at [SLIP * 2 + 1];  // at[d + SLIP] = hits at e + d, in LOCK when pos = e + SLIP
    logic            judge, found, slip, lose, verify_due, confirm, push, drop;
    logic [POS_BITS-1:0] asm_pos;
    logic [HW-1:0]       asm_hyp;
    logic [4:0]          misses_d;

    always_comb begin
        warm = warm_q || pos_q == WARM;
        at[2*SLIP] = hit_i;
        for (int i = 0; i < 2 * SLIP; i++) at[2*SLIP - 1 - i] = hist_q[i];

        judge    = locked_q && pos_q == exp_q + POS_BITS'(SLIP);
        found    = 1'b0;
        slip     = 1'b0;
        asm_pos  = exp_q;
        asm_hyp  = lhyp_q;
        if (at[SLIP][lhyp_q]) begin
            found = 1'b1;
        end else begin
            // nearest first: 0, -1, +1, -2, +2 (sorted(range(-SLIP, SLIP + 1), key=abs))
            for (int k = 0; k < 2 * SLIP + 1; k++) begin
                automatic int d = (k + 1) / 2 * ((k % 2 == 1) ? -1 : 1);
                if (!found && |at[SLIP + d]) begin
                    found   = 1'b1;
                    slip    = 1'b1;
                    asm_pos = exp_q + POS_BITS'(d);
                    asm_hyp = lowest(at[SLIP + d]);
                end
            end
        end
        misses_d = found ? 5'd0 : misses_q + 5'd1;
        lose     = judge && misses_d > {1'b0, flywheel_i};

        verify_due = !locked_q && qcount_q != '0 && qpos_q[0] + POS_BITS'(FRAME) == pos_q;
        confirm    = verify_due && hit_i[qhyp_q[0]];
        push       = !locked_q && !confirm && |hit_i;
        drop       = push && (qcount_q - QW'(verify_due)) == QW'(CANDIDATES);

        for (int i = 0; i < 2; i++) begin
            d_valid_o[i] = 1'b0;
            d_first_o[i] = '0;
            d_hyp_o[i]   = '0;
            d_fly_o[i]   = 1'b0;
        end
        if (en_i && judge && !lose) begin
            d_valid_o[0] = 1'b1;
            d_first_o[0] = asm_pos - POS_BITS'(ASM_TRANSIENT + PRE);
            d_hyp_o[0]   = asm_hyp;
            d_fly_o[0]   = misses_d != 5'd0;
        end
        if (en_i && confirm) begin
            d_valid_o[0] = !qearly_q[0];
            d_first_o[0] = qpos_q[0] - POS_BITS'(ASM_TRANSIENT + PRE);
            d_hyp_o[0]   = qhyp_q[0];
            d_valid_o[1] = 1'b1;
            d_first_o[1] = pos_q - POS_BITS'(ASM_TRANSIENT + PRE);
            d_hyp_o[1]   = qhyp_q[0];
        end
    end

    // ---- state update
    always_ff @(posedge clk_i) begin
        if (rst_i) begin
            pos_q     <= '0;
            warm_q    <= 1'b0;
            for (int i = 0; i < 2 * SLIP; i++) hist_q[i] <= '0;
            locked_q  <= 1'b0;
            exp_q     <= '0;
            lhyp_q    <= '0;
            misses_q  <= '0;
            qcount_q  <= '0;
            dropped_q <= '0;
            slips_q   <= '0;
            early_q   <= '0;
        end else if (en_i) begin
            pos_q  <= pos_q + 1'b1;
            warm_q <= warm;
            hist_q[0] <= hit_i;
            for (int i = 1; i < 2 * SLIP; i++) hist_q[i] <= hist_q[i-1];

            if (judge) begin
                if (lose) begin
                    locked_q <= 1'b0;
                end else begin
                    exp_q    <= asm_pos + POS_BITS'(FRAME);
                    lhyp_q   <= asm_hyp;
                    misses_q <= misses_d;
                    if (slip) slips_q <= sat_inc(slips_q);
                end
            end

            if (confirm) begin
                locked_q <= 1'b1;
                exp_q    <= pos_q + POS_BITS'(FRAME);
                lhyp_q   <= qhyp_q[0];
                misses_q <= '0;
                qcount_q <= '0;
                if (qearly_q[0]) early_q <= sat_inc(early_q);
            end else if (!locked_q) begin
                // pop the peak that came due, then queue the new one behind the survivors
                automatic logic [QW-1:0] n = qcount_q;
                if (verify_due) begin
                    for (int i = 0; i < CANDIDATES - 1; i++) begin
                        qpos_q[i]   <= qpos_q[i+1];
                        qhyp_q[i]   <= qhyp_q[i+1];
                        qearly_q[i] <= qearly_q[i+1];
                    end
                    n = n - 1'b1;
                end
                if (push) begin
                    if (drop) begin
                        dropped_q <= sat_inc(dropped_q);
                    end else begin
                        qpos_q[QI'(n)]   <= pos_q;
                        qhyp_q[QI'(n)]   <= lowest(hit_i);
                        qearly_q[QI'(n)] <= !warm;
                        n = n + 1'b1;
                    end
                end
                qcount_q <= n;
            end
        end
    end

    assign locked_o  = locked_q;
    assign dropped_o = dropped_q;
    assign slips_o   = slips_q;
    assign early_o   = early_q;

endmodule

`default_nettype wire
