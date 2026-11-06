`default_nettype none

// Viterbi branch metrics for one trellis step (Phase D; bit-true model: model/viterbi_fixed.py acs()).
//
// a_i, b_i: the step's two quantized soft symbols (G1 then G2), unsigned offset binary, large = bit 1
// (viterbi_fixed.quantize()). The distance to an expected 1 is TOP - u, to an expected 0 is u, so
// bm_o[{g1, g2}] = dist(a, g1) + dist(b, g2) for the four possible coded-bit pairs. Combinational.
module fec_bm #(
    parameter int SOFT_BITS = 4  // ADR 0005
) (
    input  wire logic [SOFT_BITS-1:0] a_i,
    input  wire logic [SOFT_BITS-1:0] b_i,
    output      logic [3:0][SOFT_BITS:0] bm_o  // index {expected G1 bit, expected G2 bit}
);

    localparam logic [SOFT_BITS-1:0] TOP = '1;  // viterbi_fixed: top = 2^bits - 1

    always_comb begin
        for (int k = 0; k < 4; k++) begin
            bm_o[k] = {1'b0, (k[1] ? TOP - a_i : a_i)} + {1'b0, (k[0] ? TOP - b_i : b_i)};
        end
    end

endmodule

`default_nettype wire
