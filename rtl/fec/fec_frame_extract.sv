`default_nettype none

// Frame bits out of the Viterbi's continuous output, NRZ-M decoded, with each window's flags (ADR 0010 amendment,
// ADR 0001; bit-true model: model/cadu_fixed.py cadus_from_windows(), the bits before frame_to_cadu()).
//
// The Viterbi decides window w's step j as its output bit w * STEPS + j (it never resets between windows and every
// window is STEPS steps long; framesync_fixed.decode_windows()), so a counter mod STEPS on the output finds the
// frame: bits FIRST .. FIRST + FRAME_BITS - 1, NRZ-M decoded from bit FIRST - 1. The other bits (run-in, run-out)
// are consumed and not passed on, by design.
//
// Flags: the window's {flywheel, swap, alternate} are taken from the Viterbi's input at each window's first beat
// (win_*: a tap on the fec_framesync -> fec_viterbi stream) into a FLAG_DEPTH FIFO, and leave with the window's
// frame. A window can only be in flight between the two for one window plus the traceback depth, so the FIFO cannot
// overflow in operation; if it ever does, flag_ovf_o counts it.
//
// Out: m_tdata = one frame bit per beat, m_tuser = flags (constant over the frame), m_tlast on its last bit.
module fec_frame_extract #(
    parameter int STEPS      = 8352,  // framesync_fixed.WINDOW_SYMBOLS / 2
    parameter int FIRST      = 64,    // framesync_fixed.PRE_SYMBOLS / 2: the frame's first bit in its window
    parameter int FRAME_BITS = 8192,  // model/coding.py CADU_BITS
    parameter int FLAG_DEPTH = 4,
    parameter int COUNT_BITS = 16
) (
    input  wire logic                  clk_i,
    input  wire logic                  rst_i,

    // tap on the Viterbi's input handshake (fec_framesync m_*)
    input  wire logic                  win_hs_i,     // a beat was accepted by the Viterbi
    input  wire logic                  win_last_i,   // that beat was the window's last
    input  wire logic [2:0]            win_tuser_i,  // {flywheel, swap, alternate}

    input  wire logic                  s_tdata_i,    // Viterbi output bit
    input  wire logic                  s_tvalid_i,
    output      logic                  s_tready_o,

    output      logic                  m_tdata_o,
    output      logic [2:0]            m_tuser_o,
    output      logic                  m_tlast_o,
    output      logic                  m_tvalid_o,
    input  wire logic                  m_tready_i,

    output      logic [COUNT_BITS-1:0] flag_ovf_o
);

    localparam int STEP_BITS = $clog2(STEPS);
    localparam int FB        = $clog2(FLAG_DEPTH);

    // ---- flag FIFO --------------------------------------------------------------------------------------------------
    logic           win_first_q;  // the next accepted window beat is a window's first
    logic [2:0]     flags_mem [FLAG_DEPTH];
    logic [FB-1:0]  fw_q, fr_q;
    logic [FB:0]    fcnt_q;
    logic           push, pop;

    assign push = win_hs_i && win_first_q && fcnt_q != (FB+1)'(FLAG_DEPTH);

    always_ff @(posedge clk_i) begin
        if (push) flags_mem[fw_q] <= win_tuser_i;
    end

    // ---- window counter, NRZ-M --------------------------------------------------------------------------------------
    logic [STEP_BITS-1:0] j_q;
    logic                 prev_q;
    logic                 in_frame, at_prev, at_end, accept;

    assign in_frame   = j_q >= STEP_BITS'(FIRST) && j_q < STEP_BITS'(FIRST + FRAME_BITS);
    assign at_prev    = j_q == STEP_BITS'(FIRST - 1);
    assign at_end     = j_q == STEP_BITS'(STEPS - 1);
    // Bits outside the frame are taken unconditionally; frame bits only when the output can take them.
    assign s_tready_o = !in_frame || m_tready_i;
    assign accept     = s_tvalid_i && s_tready_o;

    assign m_tvalid_o = s_tvalid_i && in_frame;
    assign m_tdata_o  = s_tdata_i ^ prev_q;
    assign m_tlast_o  = j_q == STEP_BITS'(FIRST + FRAME_BITS - 1);
    assign m_tuser_o  = flags_mem[fr_q];
    // A window's flags leave with its last step; by then the frame has used them.
    assign pop        = accept && at_end;

    always_ff @(posedge clk_i) begin
        if (rst_i) begin
            j_q         <= '0;
            prev_q      <= 1'b0;
            win_first_q <= 1'b1;
            fw_q        <= '0;
            fr_q        <= '0;
            fcnt_q      <= '0;
            flag_ovf_o  <= '0;
        end else begin
            if (accept) begin
                j_q <= at_end ? '0 : j_q + STEP_BITS'(1);
                if (at_prev || in_frame) prev_q <= s_tdata_i;
            end
            if (win_hs_i) win_first_q <= win_last_i;
            if (win_hs_i && win_first_q && !push && flag_ovf_o != '1) flag_ovf_o <= flag_ovf_o + COUNT_BITS'(1);
            if (push) fw_q <= fw_q + FB'(1);
            if (pop)  fr_q <= fr_q + FB'(1);
            case ({push, pop})
                2'b10:   fcnt_q <= fcnt_q + (FB+1)'(1);
                2'b01:   fcnt_q <= fcnt_q - (FB+1)'(1);
                default: ;
            endcase
        end
    end

`ifndef SYNTHESIS
    // Coverage bins (make cov, docs/coverage.md): backpressure on each interface.
    cov_bp_s: cover property (@(posedge clk_i) disable iff (rst_i) s_tvalid_i && !s_tready_o);
    cov_bp_m: cover property (@(posedge clk_i) disable iff (rst_i) m_tvalid_o && !m_tready_i);
`endif

endmodule

`default_nettype wire
