`default_nettype none

// Frame sync delay line and Viterbi feed (ADR 0010; bit-true model: model/framesync_fixed.py windows()).
//
// Every input symbol is written to a DEPTH-symbol block-RAM ring at its absolute index w. For each frame descriptor
// (window first symbol s - PRE for frame start s, hypothesis, flywheel flag; fec_fs_fsm), once symbol
// s + FRAME + POST - 1 is written, the reader sends window [s - PRE, s + FRAME + POST) to the Viterbi, derotated
// (framesync_fixed.undo_levels(): alternate inverts every odd symbol, swap exchanges each pair) and paired. Windows
// are read by address, so they may overlap.
//
// Out: m_tdata = {b, a} (fec_viterbi's input), m_tuser = {flywheel, swap, alternate}, m_tlast on a window's last
// pair. Two RAM reads per pair (a few clocks), against ~100 clocks per Viterbi step.
//
// Input backpressure, never a drop: s_tready falls while writing would overwrite a symbol the reader or a pending
// window still needs, or while the descriptor FIFO has fewer than 2 free entries (the FSM can emit 2 on one symbol).
// Neither can deadlock: a window becomes readable once WINDOW symbols past its first are written, WINDOW < DEPTH,
// and at most 2 descriptors can be waiting on input (their starts are about a frame apart and each is emitted ~67
// symbols after its ASM), so with DESC = 4 the FIFO only fills while the head is readable.
module fec_fs_window #(
    parameter int SOFT_BITS = 4,      // ADR 0005
    parameter int FRAME     = 16384,  // model/coding.py CODED_FRAME_SYMBOLS
    parameter int PRE       = 128,    // framesync_fixed.PRE_SYMBOLS
    parameter int POST      = 192,    // framesync_fixed.POST_SYMBOLS = 2 * traceback depth
    parameter int DEPTH     = 32768,  // > PRE + FRAME + POST + the ~200-symbol decision lag; a power of two
    parameter int DESC      = 4,      // descriptor FIFO; >= 4, see above
    parameter int POS_BITS  = 32,
    parameter int HYPS      = 4
) (
    input  wire logic                    clk_i,
    input  wire logic                    rst_i,

    input  wire logic [SOFT_BITS-1:0]    s_tdata_i,
    input  wire logic                    s_tvalid_i,
    output      logic                    s_tready_o,

    input  wire logic                    d_valid_i [2],  // oldest on port 0; written in the input beat's clock
    input  wire logic [POS_BITS-1:0]     d_first_i [2],
    input  wire logic [$clog2(HYPS)-1:0] d_hyp_i   [2],
    input  wire logic                    d_fly_i   [2],

    output      logic [2*SOFT_BITS-1:0]  m_tdata_o,
    output      logic [2:0]              m_tuser_o,
    output      logic                    m_tlast_o,
    output      logic                    m_tvalid_o,
    input  wire logic                    m_tready_i
);

    localparam int WINDOW = PRE + FRAME + POST;  // framesync_fixed.WINDOW_SYMBOLS, even
    localparam int AW     = $clog2(DEPTH);
    localparam int PW     = $clog2(WINDOW / 2 + 1);
    localparam int DW     = $clog2(DESC);
    localparam int HW     = $clog2(HYPS);

    // ---- ring
    logic [SOFT_BITS-1:0] mem [DEPTH];
    logic [POS_BITS-1:0]  w_q;  // index of the next symbol written
    logic [AW-1:0]        raddr;
    logic [SOFT_BITS-1:0] rdata_q;
    logic                 beat;

    assign beat = s_tvalid_i && s_tready_o;

    always_ff @(posedge clk_i) begin
        if (beat) mem[w_q[AW-1:0]] <= s_tdata_i;
        rdata_q <= mem[raddr];
    end

    // ---- descriptor FIFO
    logic [POS_BITS-1:0] f_first [DESC];
    logic [HW-1:0]       f_hyp   [DESC];
    logic                f_fly   [DESC];
    logic [DW-1:0]       f_rd_q, f_wr_q;
    logic [DW:0]         f_count_q;
    logic                pop;

    // ---- reader
    typedef enum logic [1:0] {IDLE, RD0, RD1, OUT} state_t;
    state_t               state_q;
    logic [POS_BITS-1:0]  r_q;      // next symbol to read
    logic [PW-1:0]        left_q;   // pairs left in the window, including the one in m_tdata
    logic                 alt_q, swap_q, fly_q;
    logic [SOFT_BITS-1:0] sym0_q;
    logic [POS_BITS-1:0]  head_first;
    logic                 head_ready;

    always_comb begin
        head_first = f_first[f_rd_q];
        head_ready = f_count_q != '0 && (w_q - head_first) >= POS_BITS'(WINDOW);
        pop        = state_q == IDLE && head_ready;
        raddr      = state_q == RD1 ? AW'(r_q + 1'b1) : r_q[AW-1:0];  // RD0 reads r, RD1 reads r + 1
    end

    // Writing symbol w overwrites w - DEPTH. Still needed: the reader's position and the head window's first symbol,
    // which can be the older of the two, since consecutive windows overlap by PRE + POST. s_tready is a register (it
    // would otherwise sit in a loop through the FSM back into the FIFO), so it is computed for the next clock: room
    // with one symbol of margin (at most one is written meanwhile), FIFO space from the count after this clock's
    // pushes and pop. A descriptor pushed meanwhile starts ~FRAME + 200 symbols back, far from DEPTH.
    logic busy, room, space_d;
    logic [DW:0] f_count_d;
    always_comb begin
        busy = state_q != IDLE;
        room = (!busy || (w_q - r_q) < POS_BITS'(DEPTH - 1))
            && (f_count_q == '0 || (w_q - head_first) < POS_BITS'(DEPTH - 1));
        f_count_d = f_count_q - (DW + 1)'(pop) + (DW + 1)'(d_valid_i[0]) + (DW + 1)'(d_valid_i[1]);
        space_d   = f_count_d <= (DW + 1)'(DESC - 2);
    end

    always_ff @(posedge clk_i) begin
        if (rst_i) begin
            w_q       <= '0;
            f_rd_q    <= '0;
            f_wr_q    <= '0;
            f_count_q <= '0;
            state_q   <= IDLE;
            m_tvalid_o <= 1'b0;
            s_tready_o <= 1'b0;
        end else begin
            if (beat) w_q <= w_q + 1'b1;
            s_tready_o <= room && space_d;

            // FIFO: up to 2 pushes per beat, at most 1 pop per clock
            begin
                automatic logic [DW-1:0] wr = f_wr_q;
                for (int i = 0; i < 2; i++) begin
                    if (d_valid_i[i]) begin
                        f_first[wr] <= d_first_i[i];
                        f_hyp[wr]   <= d_hyp_i[i];
                        f_fly[wr]   <= d_fly_i[i];
                        wr = wr + 1'b1;
                    end
                end
                f_wr_q    <= wr;
                f_count_q <= f_count_d;
                if (pop) f_rd_q <= f_rd_q + 1'b1;
            end

            case (state_q)
                IDLE: if (pop) begin
                    r_q     <= head_first;
                    left_q  <= PW'(WINDOW / 2);
                    alt_q   <= f_hyp[f_rd_q][0];
                    swap_q  <= f_hyp[f_rd_q][1];
                    fly_q   <= f_fly[f_rd_q];
                    state_q <= RD0;
                end
                RD0: state_q <= RD1;  // rdata_q <= symbol r
                RD1: begin            // rdata_q <= symbol r + 1
                    sym0_q  <= rdata_q;
                    state_q <= OUT;
                end
                OUT: begin
                    if (!m_tvalid_o) begin
                        // derotate and pair: a = G1, b = G2 (receiver._undo_hypothesis(): alternate, then swap)
                        automatic logic [SOFT_BITS-1:0] x1 = alt_q ? ~rdata_q : rdata_q;
                        m_tdata_o  <= swap_q ? {sym0_q, x1} : {x1, sym0_q};
                        m_tuser_o  <= {fly_q, swap_q, alt_q};
                        m_tlast_o  <= left_q == PW'(1);
                        m_tvalid_o <= 1'b1;
                        r_q        <= r_q + POS_BITS'(2);
                    end else if (m_tready_i) begin
                        m_tvalid_o <= 1'b0;
                        left_q     <= left_q - 1'b1;
                        state_q    <= left_q == PW'(1) ? IDLE : RD0;
                    end
                end
                default: state_q <= IDLE;
            endcase
        end
    end

`ifndef SYNTHESIS
    // The FSM pushes only when there is room (s_tready required 2 free on its beat).
    a_fifo_no_overflow: assert property (@(posedge clk_i) disable iff (rst_i) f_count_q <= (DW + 1)'(DESC));
    // A pair is read only after both symbols are written and before either is overwritten.
    a_read_in_ring: assert property (@(posedge clk_i) disable iff (rst_i)
        (state_q == RD0 || state_q == RD1) |-> (w_q - r_q) >= POS_BITS'(2) && (w_q - r_q) <= POS_BITS'(DEPTH))
        else $error("ring read r=%0d with w=%0d", r_q, w_q);
`endif

`ifndef SYNTHESIS
    // Coverage bins (make cov, docs/coverage.md): backpressure on each interface.
    cov_bp_s: cover property (@(posedge clk_i) disable iff (rst_i) s_tvalid_i && !s_tready_o);
    cov_bp_m: cover property (@(posedge clk_i) disable iff (rst_i) m_tvalid_o && !m_tready_i);
`endif

endmodule

`default_nettype wire
