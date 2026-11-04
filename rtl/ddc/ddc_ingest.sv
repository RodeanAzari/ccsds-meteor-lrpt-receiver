`default_nettype none

// Ingest + DC block (Phase B, docs/fixed-point.md §DDC; bit-true model: model/ddc_fixed.py ingest(), dc_block()).
//
// In:  one cu8 sample per beat, s_tdata = {Q_u8, I_u8} (the replay byte order I, Q read as a little-endian 16-bit word).
// Out: m_tdata = {Q, I}, each s10.
//
// Per rail: v = 2*raw - 255 (s9, exact), then
//   acc += ((v - prev) << DC_FRAC) - round(acc >> DC_K)      (pole 1 - 2^-DC_K)
//   y    = sat(round(acc >> DC_FRAC), OUT_W)
// One output register; s_tready = !m_tvalid || m_tready, so nothing is dropped under backpressure.
module ddc_ingest #(
    parameter int IN_W   = 8,   // cu8 per rail, signal-spec.md
    parameter int DC_K   = 10,  // pole 1 - 2^-10, corner 159 Hz at 1.024 MS/s; fixed-point.md §DDC
    parameter int DC_FRAC = 12, // accumulator fraction bits; fixed-point.md §DDC
    parameter int ACC_W  = 24,  // |acc| <= 2*255 * 2^12 < 2^21 (HPF sum|h| = 2); fixed-point.md §DDC
    parameter int OUT_W  = 10   // a DC step can double the swing: +-510; fixed-point.md §DDC
) (
    input  wire logic                 clk_i,
    input  wire logic                 rst_i,

    input  wire logic [2*IN_W-1:0]    s_tdata_i,
    input  wire logic                 s_tvalid_i,
    output      logic                 s_tready_o,

    output      logic [2*OUT_W-1:0]   m_tdata_o,
    output      logic                 m_tvalid_o,
    input  wire logic                 m_tready_i
);

    localparam int V_W = IN_W + 1;  // 2*raw - 255 is s9 for IN_W = 8

    logic signed [ACC_W-1:0] acc_q  [2];
    logic signed [V_W-1:0]   prev_q [2];
    logic signed [ACC_W-1:0] acc_d  [2];
    logic signed [V_W-1:0]   v      [2];
    logic signed [OUT_W-1:0] y      [2];
    logic                    take;

    assign s_tready_o = !m_tvalid_o || m_tready_i;
    assign take       = s_tvalid_i && s_tready_o;

    function automatic logic signed [OUT_W-1:0] sat_round(input logic signed [ACC_W-1:0] a);
        logic signed [ACC_W-1:0] r;
        r = (a + ACC_W'(1 << (DC_FRAC - 1))) >>> DC_FRAC;
        if (r > ACC_W'((1 << (OUT_W - 1)) - 1))       return {1'b0, {(OUT_W-1){1'b1}}};
        else if (r < -ACC_W'(1 << (OUT_W - 1)))       return {1'b1, {(OUT_W-1){1'b0}}};
        else                                          return r[OUT_W-1:0];
    endfunction

    always_comb begin
        for (int r = 0; r < 2; r++) begin
            v[r] = V_W'({1'b0, s_tdata_i[r*IN_W +: IN_W], 1'b0}) - V_W'((1 << IN_W) - 1);
            acc_d[r] = acc_q[r]
                     + ((ACC_W'(v[r]) - ACC_W'(prev_q[r])) <<< DC_FRAC)  // widen first: v - prev needs s10
                     - ((acc_q[r] + ACC_W'(1 << (DC_K - 1))) >>> DC_K);
            y[r] = sat_round(acc_d[r]);
        end
    end

    always_ff @(posedge clk_i) begin
        if (rst_i) begin
            m_tvalid_o <= 1'b0;
            for (int r = 0; r < 2; r++) begin
                acc_q[r]  <= '0;
                prev_q[r] <= '0;
            end
        end else begin
            if (take) begin
                for (int r = 0; r < 2; r++) begin
                    acc_q[r]  <= acc_d[r];
                    prev_q[r] <= v[r];
                end
                m_tdata_o <= {y[1], y[0]};
            end
            if (take)            m_tvalid_o <= 1'b1;
            else if (m_tready_i) m_tvalid_o <= 1'b0;
        end
    end

endmodule

`default_nettype wire
