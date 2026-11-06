`default_nettype none

// Viterbi survivor memory and sliding traceback (ADRs 0007, 0008; bit-true model: model/viterbi_fixed.py
// traceback_sliding() with start "zero").
//
// In:  s_tdata = one step's 64 decision bits (fec_acs_array), written to a ROWS-deep BRAM ring.
// Out: m_tdata = one decoded bit per step once depth_i + 1 rows are in: for row t, walk back depth_i rows from state
//      0, state <- {row[state], state[5:1]}, and output bit 0 of the state reached, which is the bit of step
//      t - depth_i. The row addresses are known in advance, so one BRAM read per clock; only the 64:1 select
//      depends on the state. depth_i + 3 clocks per bit (ADR 0007); a new row is accepted only between walks.
// depth_i is a control register (ADR 0008: 96), 1 to ROWS - 1, held constant while running.
module fec_traceback #(
    parameter int ROWS = 256  // ADR 0008: room for the depth with margin; one block RAM
) (
    input  wire logic                    clk_i,
    input  wire logic                    rst_i,
    input  wire logic [$clog2(ROWS)-1:0] depth_i,

    input  wire logic [63:0]             s_tdata_i,
    input  wire logic                    s_tvalid_i,
    output      logic                    s_tready_o,

    output      logic                    m_tdata_o,
    output      logic                    m_tvalid_o,
    input  wire logic                    m_tready_i
);

    localparam int AW = $clog2(ROWS);

    logic [63:0]   mem [ROWS];
    logic [63:0]   rdata_q;
    logic [AW-1:0] wr_ptr_q, rd_ptr_q;
    logic [AW-1:0] issue_q, use_q;  // reads still to issue / rows still to use in this walk
    logic [AW:0]   filled_q;        // rows written, saturating at ROWS
    logic          busy_q, rd_valid_q;
    logic [5:0]    state_q, state_d;

    assign s_tready_o = !busy_q && !m_tvalid_o;
    assign state_d    = {rdata_q[state_q], state_q[5:1]};

    always_ff @(posedge clk_i) begin
        if (s_tvalid_i && s_tready_o) mem[wr_ptr_q] <= s_tdata_i;
        rdata_q <= mem[rd_ptr_q];
    end

    always_ff @(posedge clk_i) begin
        if (rst_i) begin
            wr_ptr_q   <= '0;
            filled_q   <= '0;
            busy_q     <= 1'b0;
            rd_valid_q <= 1'b0;
            m_tvalid_o <= 1'b0;
        end else begin
            if (m_tready_i) m_tvalid_o <= 1'b0;
            if (s_tvalid_i && s_tready_o) begin
                wr_ptr_q <= wr_ptr_q + 1'b1;
                if (filled_q != (AW+1)'(ROWS)) filled_q <= filled_q + 1'b1;
                if (filled_q >= {1'b0, depth_i}) begin  // this row is t >= depth: walk back from it
                    busy_q   <= 1'b1;
                    rd_ptr_q <= wr_ptr_q;
                    issue_q  <= depth_i;
                    use_q    <= depth_i;
                    state_q  <= '0;  // ADR 0008: start from state 0
                end
            end
            if (busy_q) begin
                rd_valid_q <= issue_q != '0;
                if (issue_q != '0) begin
                    rd_ptr_q <= rd_ptr_q - 1'b1;
                    issue_q  <= issue_q - 1'b1;
                end
                if (rd_valid_q) begin
                    state_q <= state_d;
                    use_q   <= use_q - 1'b1;
                    if (use_q == AW'(1)) begin
                        busy_q     <= 1'b0;
                        rd_valid_q <= 1'b0;
                        m_tdata_o  <= state_d[0];
                        m_tvalid_o <= 1'b1;
                    end
                end
            end
        end
    end

endmodule

`default_nettype wire
