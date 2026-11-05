`default_nettype none

// UART transmitter, 8N1, LSB first, idle high. Bytes arrive as an AXI-Stream; s_tready is high only when idle.
module uart_tx #(
    parameter int CLKS_PER_BIT = 868  // 100 MHz / 115,200 baud
) (
    input  wire logic       clk_i,
    input  wire logic       rst_i,
    input  wire logic [7:0] s_tdata_i,
    input  wire logic       s_tvalid_i,
    output      logic       s_tready_o,
    output      logic       txd_o
);

    localparam int CW = $clog2(CLKS_PER_BIT);

    logic [8:0]   shift_q;  // {stop, data[7:0]}, shifted out LSB first after the start bit
    logic [3:0]   bits_q;   // bits left to send, including the one on the line
    logic [CW-1:0] cnt_q;

    assign s_tready_o = bits_q == '0;

    always_ff @(posedge clk_i) begin
        if (rst_i) begin
            bits_q <= '0;
            cnt_q  <= '0;
            txd_o  <= 1'b1;
        end else if (bits_q == '0) begin
            txd_o <= 1'b1;
            if (s_tvalid_i) begin
                shift_q <= {1'b1, s_tdata_i};
                bits_q  <= 4'd10;
                cnt_q   <= '0;
                txd_o   <= 1'b0;  // start bit goes out now
            end
        end else if (cnt_q == CW'(CLKS_PER_BIT - 1)) begin
            cnt_q   <= '0;
            bits_q  <= bits_q - 1'b1;
            shift_q <= {1'b1, shift_q[8:1]};
            txd_o   <= shift_q[0];  // data bits, then stop, then idle (all ones shifted in)
        end else begin
            cnt_q <= cnt_q + 1'b1;
        end
    end

endmodule

`default_nettype wire
