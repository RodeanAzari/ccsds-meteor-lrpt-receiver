`default_nettype none

// CIC decimator, both rails (Phase B; ADR 0004; docs/fixed-point.md §DDC; bit-true model: model/ddc_fixed.py
// cic_decimate()).
//
// In:  s_tdata = {Q, I}, each s16, 1.024 MS/s.   Out: m_tdata = {Q, I}, each s16, one per DECIM inputs (256 kS/s).
// ORDER integrators at the input rate, decimate (keep inputs DECIM-1, 2*DECIM-1, ...), ORDER combs (M = 1).
// Integrator and comb registers are REG_W bits and wrap by design (Hogenauer); the comb output is still exact.
// Output = sat(round(comb >> SHIFT)), removing the gain DECIM^ORDER = 2^SHIFT exactly.
// The integrator chain is zero-latency (int_k += new int_{k-1}), matching the model's cascaded cumsum.
// The combs run at the output rate, so they are pipelined one stage per comb: the last integrator is captured at
// the decimation instant (dump) and the result reaches the output register ORDER cycles later. A dump is accepted
// only when the comb pipe is idle and the output register empty; the DECIM-1 non-dump inputs between dumps are
// accepted freely, so at full rate (DECIM >= ORDER + 1 cycles between dumps) this costs no throughput.
module ddc_cic #(
    parameter int IN_W  = 16,  // mixer output; fixed-point.md §DDC
    parameter int ORDER = 3,   // ADR 0004
    parameter int DECIM = 4,   // ADR 0004; must be a power of two
    parameter int SHIFT = 6,   // log2(DECIM^ORDER) = 3 * 2; ADR 0004
    parameter int REG_W = 22,  // Hogenauer: IN_W + ORDER*log2(DECIM) = 16 + 6; ADR 0004
    parameter int OUT_W = 16   // fixed-point.md §DDC
) (
    input  wire logic               clk_i,
    input  wire logic               rst_i,

    input  wire logic [2*IN_W-1:0]  s_tdata_i,
    input  wire logic               s_tvalid_i,
    output      logic               s_tready_o,

    output      logic [2*OUT_W-1:0] m_tdata_o,
    output      logic               m_tvalid_o,
    input  wire logic               m_tready_i
);

    localparam int CNT_W = $clog2(DECIM);

    logic signed [REG_W-1:0] integ_q [2][ORDER];
    logic signed [REG_W-1:0] integ_d [2][ORDER];
    logic signed [REG_W-1:0] dly_q   [2][ORDER];  // comb delay elements, at the output rate
    logic signed [REG_W-1:0] comb_q  [2][ORDER];  // comb_q[r][0] is the captured integrator, then comb k-1 output
    logic signed [REG_W-1:0] last    [2];
    logic [ORDER-1:0]        cvld_q;              // comb pipe stage valid
    logic [CNT_W-1:0]        phase_q;
    logic                    at_dump, take, dump;

    assign at_dump    = phase_q == CNT_W'(DECIM - 1);
    assign s_tready_o = !at_dump || (cvld_q == '0 && !m_tvalid_o);
    assign take       = s_tvalid_i && s_tready_o;
    assign dump       = take && at_dump;

    function automatic logic signed [OUT_W-1:0] sat_round(input logic signed [REG_W-1:0] x);
        logic signed [REG_W:0] r;  // one extra bit so adding the rounding half cannot wrap
        r = ((REG_W+1)'(x) + (REG_W+1)'(1 << (SHIFT - 1))) >>> SHIFT;
        if (r > (REG_W+1)'((1 << (OUT_W - 1)) - 1)) return {1'b0, {(OUT_W-1){1'b1}}};
        else if (r < -(REG_W+1)'(1 << (OUT_W - 1))) return {1'b1, {(OUT_W-1){1'b0}}};
        else                                        return r[OUT_W-1:0];
    endfunction

    always_comb begin
        for (int r = 0; r < 2; r++) begin
            integ_d[r][0] = integ_q[r][0] + REG_W'($signed(s_tdata_i[r*IN_W +: IN_W]));
            for (int k = 1; k < ORDER; k++) integ_d[r][k] = integ_q[r][k] + integ_d[r][k-1];
            last[r] = comb_q[r][ORDER-1] - dly_q[r][ORDER-1];
        end
    end

    always_ff @(posedge clk_i) begin
        if (rst_i) begin
            phase_q    <= '0;
            cvld_q     <= '0;
            m_tvalid_o <= 1'b0;
            for (int r = 0; r < 2; r++)
                for (int k = 0; k < ORDER; k++) begin
                    integ_q[r][k] <= '0;
                    dly_q[r][k]   <= '0;
                end
        end else begin
            if (take) begin
                phase_q <= phase_q + 1'b1;
                integ_q <= integ_d;
            end
            cvld_q <= {cvld_q[ORDER-2:0], dump};
            for (int r = 0; r < 2; r++) begin
                if (dump) comb_q[r][0] <= integ_d[r][ORDER-1];
                for (int k = 1; k < ORDER; k++)
                    if (cvld_q[k-1]) begin
                        comb_q[r][k]  <= comb_q[r][k-1] - dly_q[r][k-1];
                        dly_q[r][k-1] <= comb_q[r][k-1];
                    end
                if (cvld_q[ORDER-1]) dly_q[r][ORDER-1] <= comb_q[r][ORDER-1];
            end
            if (cvld_q[ORDER-1]) m_tdata_o <= {sat_round(last[1]), sat_round(last[0])};
            if (cvld_q[ORDER-1]) m_tvalid_o <= 1'b1;
            else if (m_tready_i) m_tvalid_o <= 1'b0;
        end
    end

endmodule

`default_nettype wire
