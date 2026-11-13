`default_nettype none

// Two packet streams -> one, whole packets at a time, for fpga-eth-core's udp_tx (which has no arbiter and takes one
// payload per tlast). In arty_rx_eth_top: s0 = CADU packets (cadu_packet), s1 = stats packets (stats_packet).
//
// A grant is taken only while idle, from the sources whose tvalid is high; when both are, the one not served last
// wins (round robin), so neither can starve the other. The grant holds until the granted source's tlast handshake,
// so a packet's bytes are never interleaved with the other's. While granted, the source's tvalid/tdata/tlast pass
// through combinationally and m_tready goes back to it alone; the other source sees tready low. No storage: nothing
// can be dropped or repeated. One idle clock between packets (the grant is registered).
module pkt_arb2 (
    input  wire logic       clk_i,
    input  wire logic       rst_i,

    input  wire logic [7:0] s0_tdata_i,
    input  wire logic       s0_tvalid_i,
    output      logic       s0_tready_o,
    input  wire logic       s0_tlast_i,

    input  wire logic [7:0] s1_tdata_i,
    input  wire logic       s1_tvalid_i,
    output      logic       s1_tready_o,
    input  wire logic       s1_tlast_i,

    output      logic [7:0] m_tdata_o,
    output      logic       m_tvalid_o,
    input  wire logic       m_tready_i,
    output      logic       m_tlast_o
);

    logic busy_q;  // a packet is in progress from source sel_q
    logic sel_q;   // granted source while busy_q; the source served last while idle

    always_ff @(posedge clk_i) begin
        if (rst_i) begin
            busy_q <= 1'b0;
            sel_q  <= 1'b1;  // so s0 wins the first tie
        end else if (!busy_q) begin
            if (s0_tvalid_i && s1_tvalid_i) begin
                busy_q <= 1'b1;
                sel_q  <= ~sel_q;
            end else if (s0_tvalid_i || s1_tvalid_i) begin
                busy_q <= 1'b1;
                sel_q  <= s1_tvalid_i;
            end
        end else if (m_tvalid_o && m_tready_i && m_tlast_o) begin
            busy_q <= 1'b0;
        end
    end

    always_comb begin
        m_tdata_o   = sel_q ? s1_tdata_i : s0_tdata_i;
        m_tlast_o   = sel_q ? s1_tlast_i : s0_tlast_i;
        m_tvalid_o  = busy_q && (sel_q ? s1_tvalid_i : s0_tvalid_i);
        s0_tready_o = busy_q && !sel_q && m_tready_i;
        s1_tready_o = busy_q &&  sel_q && m_tready_i;
    end

`ifndef SYNTHESIS
    // The grant cannot move inside a packet.
    a_grant: assert property (@(posedge clk_i) disable iff (rst_i)
        busy_q && !(m_tvalid_o && m_tready_i && m_tlast_o) |=> busy_q && $stable(sel_q));
    a_one_ready: assert property (@(posedge clk_i) disable iff (rst_i) !(s0_tready_o && s1_tready_o));
    // Given AXI4-Stream sources, the output holds while stalled.
    a_hold: assert property (@(posedge clk_i) disable iff (rst_i)
        m_tvalid_o && !m_tready_i |=> m_tvalid_o && $stable(m_tdata_o) && $stable(m_tlast_o));
`endif

`ifndef SYNTHESIS
    // Coverage bins (make cov, docs/coverage.md): backpressure on each interface.
    cov_bp_s0: cover property (@(posedge clk_i) disable iff (rst_i) s0_tvalid_i && !s0_tready_o);
    cov_bp_s1: cover property (@(posedge clk_i) disable iff (rst_i) s1_tvalid_i && !s1_tready_o);
    cov_bp_m: cover property (@(posedge clk_i) disable iff (rst_i) m_tvalid_o && !m_tready_i);
`endif

endmodule

`default_nettype wire
