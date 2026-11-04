`default_nettype none

// CIC decimator, both rails (Phase B; ADR 0004; docs/fixed-point.md §DDC; bit-true model: model/ddc_fixed.py
// cic_decimate()).
//
// In:  s_tdata = {Q, I}, each s16, 1.024 MS/s.   Out: m_tdata = {Q, I}, each s16, one per DECIM inputs (256 kS/s).
// ORDER integrators at the input rate, decimate (keep inputs DECIM-1, 2*DECIM-1, ...), ORDER combs (M = 1).
// Integrator and comb registers are REG_W bits and wrap by design (Hogenauer); the comb output is still exact.
// Output = sat(round(comb >> SHIFT)), removing the gain DECIM^ORDER = 2^SHIFT exactly.
// The integrator chain is zero-latency (int_k += new int_{k-1}), matching the model's cascaded cumsum.
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
    logic signed [REG_W-1:0] comb    [2][ORDER];
    logic signed [OUT_W-1:0] y       [2];
    logic [CNT_W-1:0]        phase_q;
    logic                    take, dump;

    assign s_tready_o = !m_tvalid_o || m_tready_i;
    assign take       = s_tvalid_i && s_tready_o;
    assign dump       = take && (phase_q == CNT_W'(DECIM - 1));

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
            comb[r][0] = integ_d[r][ORDER-1] - dly_q[r][0];
            for (int k = 1; k < ORDER; k++) comb[r][k] = comb[r][k-1] - dly_q[r][k];
            y[r] = sat_round(comb[r][ORDER-1]);
        end
    end

    always_ff @(posedge clk_i) begin
        if (rst_i) begin
            phase_q    <= '0;
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
            if (dump) begin
                for (int r = 0; r < 2; r++) begin
                    dly_q[r][0] <= integ_d[r][ORDER-1];
                    for (int k = 1; k < ORDER; k++) dly_q[r][k] <= comb[r][k-1];
                end
                m_tdata_o <= {y[1], y[0]};
            end
            if (dump)            m_tvalid_o <= 1'b1;
            else if (m_tready_i) m_tvalid_o <= 1'b0;
        end
    end

endmodule

`default_nettype wire
