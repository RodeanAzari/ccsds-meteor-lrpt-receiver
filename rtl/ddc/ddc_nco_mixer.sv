`default_nettype none

// NCO + complex mixer (Phase B; ADR 0003; docs/fixed-point.md §DDC; bit-true model: model/ddc_fixed.py nco(), mix()).
//
// In:  s_tdata = {Q, I}, each s10 (ddc_ingest output).
// Out: m_tdata = {Q, I}, each s16:  (I + jQ)(cos - j sin), >> MIX_SHIFT rounded, saturated.
// The k-th accepted sample after reset sees phase k * freq_word_i (mod 2^PHASE_W), as in the model.
// freq_word_i is sampled per accepted sample; the host writes it (tuning offset + Doppler pre-correction).
//
// Pipeline: P1 phase -> table address | P2 table read | P3 quadrant mirror | P4 products | P5 round/saturate.
// All stages advance together on ce = !m_tvalid || m_tready, so a stall freezes the pipe and nothing is dropped.
module ddc_nco_mixer #(
    parameter int    IN_W     = 10,   // ddc_ingest output; fixed-point.md §DDC
    parameter int    PHASE_W  = 32,   // ADR 0003
    parameter int    LUT_PH_W = 12,   // 2 quadrant + 10 address bits; ADR 0003
    parameter int    NCO_W    = 16,   // table amplitude, peak 2^15 - 1; ADR 0003
    parameter int    MIX_SHIFT = 11,  // |out| <= 11,563; fixed-point.md §DDC
    parameter int    OUT_W    = 16,   // fixed-point.md §DDC
    parameter string LUT_FILE = "nco_lut.mem"  // written by scripts/gen_rtl_tables.py from model.ddc_fixed.nco_lut()
) (
    input  wire logic               clk_i,
    input  wire logic               rst_i,
    input  wire logic [PHASE_W-1:0] freq_word_i,

    input  wire logic [2*IN_W-1:0]  s_tdata_i,
    input  wire logic               s_tvalid_i,
    output      logic               s_tready_o,

    output      logic [2*OUT_W-1:0] m_tdata_o,
    output      logic               m_tvalid_o,
    input  wire logic               m_tready_i
);

    localparam int ADDR_W = LUT_PH_W - 2;
    localparam int PROD_W = IN_W + NCO_W + 1;  // sum of two s(IN_W) x s(NCO_W) products

    // Quarter-wave sine table, theta = 2 pi (k + 0.5) / 2^LUT_PH_W. Read on two ports: sin(addr), sin(last - addr).
    logic signed [NCO_W-1:0] lut [2**ADDR_W];
    initial $readmemh(LUT_FILE, lut);

    logic ce;
    assign ce         = !m_tvalid_o || m_tready_i;
    assign s_tready_o = ce;

    logic [PHASE_W-1:0] phase_q;
    logic [4:1]         vld_q;  // valid per stage; vld_q[5] is m_tvalid_o

    // P1
    logic signed [IN_W-1:0] i1_q, q1_q;
    logic [1:0]             quad1_q;
    logic [ADDR_W-1:0]      addr1_q;
    // P2
    logic signed [IN_W-1:0]  i2_q, q2_q;
    logic [1:0]              quad2_q;
    logic signed [NCO_W-1:0] a2_q, b2_q;
    // P3
    logic signed [IN_W-1:0]  i3_q, q3_q;
    logic signed [NCO_W-1:0] cos3_q, sin3_q;
    // P4
    logic signed [PROD_W-1:0] re4_q, im4_q;

    function automatic logic signed [OUT_W-1:0] sat_round(input logic signed [PROD_W-1:0] x);
        logic signed [PROD_W-1:0] r;
        r = (x + PROD_W'(1 << (MIX_SHIFT - 1))) >>> MIX_SHIFT;
        if (r > PROD_W'((1 << (OUT_W - 1)) - 1)) return {1'b0, {(OUT_W-1){1'b1}}};
        else if (r < -PROD_W'(1 << (OUT_W - 1))) return {1'b1, {(OUT_W-1){1'b0}}};
        else                                     return r[OUT_W-1:0];
    endfunction

    always_ff @(posedge clk_i) begin
        if (rst_i) begin
            phase_q    <= '0;
            vld_q      <= '0;
            m_tvalid_o <= 1'b0;
        end else if (ce) begin
            vld_q      <= {vld_q[3:1], s_tvalid_i};
            m_tvalid_o <= vld_q[4];
            if (s_tvalid_i) phase_q <= phase_q + freq_word_i;
        end
    end

    always_ff @(posedge clk_i) begin
        if (ce) begin
            // P1: table phase is the top LUT_PH_W bits of the accumulator (truncated, ADR 0003)
            i1_q    <= s_tdata_i[IN_W-1:0];
            q1_q    <= s_tdata_i[2*IN_W-1:IN_W];
            quad1_q <= phase_q[PHASE_W-1 -: 2];
            addr1_q <= phase_q[PHASE_W-3 -: ADDR_W];
            // P2
            i2_q    <= i1_q;
            q2_q    <= q1_q;
            quad2_q <= quad1_q;
            a2_q    <= lut[addr1_q];
            b2_q    <= lut[~addr1_q];  // last - addr
            // P3: mirror the quarter wave into four quadrants
            i3_q <= i2_q;
            q3_q <= q2_q;
            unique case (quad2_q)
                2'd0: begin sin3_q <=  a2_q; cos3_q <=  b2_q; end
                2'd1: begin sin3_q <=  b2_q; cos3_q <= -a2_q; end
                2'd2: begin sin3_q <= -a2_q; cos3_q <= -b2_q; end
                2'd3: begin sin3_q <= -b2_q; cos3_q <=  a2_q; end
            endcase
            // P4: (i + jq)(cos - j sin)
            re4_q <= PROD_W'(i3_q * cos3_q) + PROD_W'(q3_q * sin3_q);
            im4_q <= PROD_W'(q3_q * cos3_q) - PROD_W'(i3_q * sin3_q);
            // P5
            m_tdata_o <= {sat_round(im4_q), sat_round(re4_q)};
        end
    end

`ifndef SYNTHESIS
    // Coverage bins (make cov, docs/coverage.md): backpressure on each interface.
    cov_bp_s: cover property (@(posedge clk_i) disable iff (rst_i) s_tvalid_i && !s_tready_o);
    cov_bp_m: cover property (@(posedge clk_i) disable iff (rst_i) m_tvalid_o && !m_tready_i);
`endif

endmodule

`default_nettype wire
