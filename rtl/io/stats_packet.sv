`default_nettype none

// Stats packet (docs/protocol.md "Board → host packets" and "Stats", type 1) as a UDP payload byte stream for
// fpga-eth-core's udp_tx: every PERIOD clocks, while enable_i is high, one packet of
//   type | version | n = N_FIELDS | pkt_seq (u32) | uptime (u64) | N_FIELDS x u32 counters, all big-endian.
// Header and counters are captured together into one shift register when the packet starts, so the counters in a
// packet are from the same clock. If the sink stalls past the next tick, that tick is kept (one pending) and the
// packet goes out as soon as the current one ends: packets are late, never interleaved or truncated. A reset
// mid-packet (the MAC restart in arty_ddc_eth_top) abandons that packet; udp_tx is reset with it.
module stats_packet #(
    parameter int         N_FIELDS = 18,
    parameter int         PERIOD   = 10_000_000,  // 100 ms at 100 MHz, docs/protocol.md STATS_PERIOD
    parameter logic [7:0] TYPE     = 8'd1,        // docs/protocol.md: 1 = stats
    parameter logic [7:0] VERSION  = 8'd1         // docs/protocol.md
) (
    input  wire logic                     clk_i,
    input  wire logic                     rst_i,
    input  wire logic                     enable_i,   // e.g. a destination is known
    input  wire logic [N_FIELDS*32-1:0]   fields_i,   // field k in bits [32k +: 32]

    output      logic [7:0]               m_tdata_o,
    output      logic                     m_tvalid_o,
    input  wire logic                     m_tready_i,
    output      logic                     m_tlast_o
);

    localparam int HDR_BYTES = 16;                       // docs/protocol.md common header
    localparam int LEN       = HDR_BYTES + 4 * N_FIELDS;
    localparam int LW        = $clog2(LEN + 1);
    localparam int PW        = $clog2(PERIOD);

    logic [LEN*8-1:0] pkt_q;      // next byte to send in the top 8 bits
    logic [LW-1:0]    left_q;     // bytes of the current packet still to send; 0 = idle
    logic [PW-1:0]    timer_q;
    logic             pending_q;
    logic [31:0]      seq_q;
    logic [63:0]      uptime_q;
    logic [N_FIELDS*32-1:0] be_fields;  // fields in send order: field 0 first, each MSB first

    always_comb begin
        for (int k = 0; k < N_FIELDS; k++) be_fields[(N_FIELDS - 1 - k) * 32 +: 32] = fields_i[k * 32 +: 32];
    end

    logic beat, tick, start;
    assign beat  = m_tvalid_o && m_tready_i;
    assign tick  = timer_q == PW'(PERIOD - 1);
    assign start = (pending_q || tick) && enable_i && (left_q == '0 || (left_q == LW'(1) && beat));

    always_ff @(posedge clk_i) begin
        if (rst_i) begin
            left_q    <= '0;
            timer_q   <= '0;
            pending_q <= 1'b0;
            seq_q     <= '0;
            uptime_q  <= '0;
        end else begin
            uptime_q <= uptime_q + 64'd1;
            timer_q  <= tick ? '0 : timer_q + PW'(1);
            if (start) begin
                pkt_q     <= {TYPE, VERSION, 16'(N_FIELDS), seq_q, uptime_q, be_fields};
                left_q    <= LW'(LEN);
                seq_q     <= seq_q + 32'd1;
                pending_q <= 1'b0;
            end else begin
                if (tick && enable_i) pending_q <= 1'b1;
                if (beat) begin
                    pkt_q  <= pkt_q << 8;
                    left_q <= left_q - LW'(1);
                end
            end
        end
    end

    assign m_tdata_o  = pkt_q[LEN*8-1 -: 8];
    assign m_tvalid_o = left_q != '0 && !rst_i;  // AXI4-Stream: TVALID low during reset, even mid-packet
    assign m_tlast_o  = left_q == LW'(1);

`ifndef SYNTHESIS
    a_hold: assert property (@(posedge clk_i) disable iff (rst_i)
        m_tvalid_o && !m_tready_i |=> m_tvalid_o && $stable(m_tdata_o) && $stable(m_tlast_o));
`endif

endmodule

`default_nettype wire
