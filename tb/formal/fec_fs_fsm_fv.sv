`default_nettype none

// Formal harness for fec_fs_fsm (tb/formal/fec_fs_fsm.sby): reset in the first cycle, en_i and hit_i free,
// flywheel_i free but constant after reset (a control register). The RTL's own SVA (inv_*) is checked, plus two
// properties over time, on the outputs:
//   a_spacing   in an unbroken lock, each frame starts FRAME +- SLIP symbols after the previous one;
//   a_flywheel  at most flywheel_i flywheel frames in a row.
// Parameters are shrunk (FRAME = 16, 8-bit positions); every property holds for any FRAME + SLIP < 2^(POS_BITS-1).
module fec_fs_fsm_fv #(
    parameter int FRAME    = 16,
    parameter int POS_BITS = 8
) (
    input wire logic       clk_i,
    input wire logic       rst_i,
    input wire logic       en_i,
    input wire logic [3:0] hit_i,
    input wire logic [3:0] flywheel_i
);

    localparam int SLIP = 2;  // fec_fs_fsm

    logic                d_valid [2];
    logic [POS_BITS-1:0] d_first [2];
    logic [1:0]          d_hyp   [2];
    logic                d_fly   [2];
    logic                locked;
    logic [3:0]          dropped, slips, early;

    fec_fs_fsm #(
        .FRAME         (FRAME),
        .ASM_TRANSIENT (2),
        .PRE           (4),
        .CANDIDATES    (4),
        .HYPS          (4),
        .POS_BITS      (POS_BITS),
        .COUNT_BITS    (4)
    ) u_dut (
        .clk_i      (clk_i),
        .rst_i      (rst_i),
        .en_i       (en_i),
        .hit_i      (hit_i),
        .flywheel_i (flywheel_i),
        .d_valid_o  (d_valid),
        .d_first_o  (d_first),
        .d_hyp_o    (d_hyp),
        .d_fly_o    (d_fly),
        .locked_o   (locked),
        .dropped_o  (dropped),
        .slips_o    (slips),
        .early_o    (early)
    );

    logic                first_q = 1'b1;
    logic [3:0]          fly_q;
    logic                have_q;   // a frame was emitted and the lock has held since
    logic [POS_BITS-1:0] last_q;   // first symbol of the newest frame emitted
    logic [3:0]          run_q;    // flywheel frames in a row
    logic                was_locked_q;

    always_ff @(posedge clk_i) begin
        first_q <= 1'b0;
        fly_q   <= flywheel_i;
    end

    always_comb begin
        if (first_q) assume (rst_i);
        if (!first_q && !rst_i) assume (flywheel_i == fly_q);
    end

    // judge emissions (in LOCK) use port 0 only; a confirm (not locked) uses both, port 1 the newer
    logic                judged, spaced;
    logic [POS_BITS-1:0] gap;
    logic [4:0]          run_d;

    always_comb begin
        judged = en_i && locked && d_valid[0];
        gap    = d_first[0] - last_q;
        spaced = gap >= POS_BITS'(FRAME - SLIP) && gap <= POS_BITS'(FRAME + SLIP);
        run_d  = d_fly[0] ? 5'(run_q) + 5'd1 : 5'd0;
    end

    always_ff @(posedge clk_i) begin
        if (rst_i) begin
            have_q       <= 1'b0;
            run_q        <= '0;
            was_locked_q <= 1'b0;
        end else begin
            was_locked_q <= locked;
            if (!locked) have_q <= 1'b0;  // before the updates below: a confirm (not yet locked) emits and sets it
            if (judged) begin
                last_q <= d_first[0];
                have_q <= 1'b1;
                run_q  <= run_d[3:0];
            end else if (en_i && d_valid[1]) begin
                last_q <= d_first[1];
                have_q <= 1'b1;
                run_q  <= '0;
            end
        end
    end

    always_comb begin
        if (!rst_i && !first_q) begin
            if (judged && have_q) a_spacing: assert (spaced);
            if (judged) a_flywheel: assert (run_d <= 5'(flywheel_i));
            // inductive helpers, true by construction: the newest frame is the one the lock projects from, and the
            // flywheel run is the FSM's miss count
            a_lock_emitted: assert (!locked || have_q);  // lock is only entered by a confirm, which emits
            if (locked && have_q) begin
                a_track_exp:    assert (last_q + POS_BITS'(2 + 4 + FRAME) == u_dut.exp_q);  // + ASM_TRANSIENT + PRE
                a_track_misses: assert (5'(run_q) == u_dut.misses_q);
            end
            // reachability: each must be hit within the cover depth
            c_lock:     cover (locked);
            c_two:      cover (en_i && d_valid[0] && d_valid[1]);
            c_slip:     cover (slips != '0);
            c_lose:     cover (was_locked_q && !locked);
            c_fly:      cover (judged && d_fly[0]);
            c_drop:     cover (dropped != '0);
            c_early:    cover (early != '0);
        end
    end

endmodule

`default_nettype wire
