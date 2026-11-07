`default_nettype none

// IQ replay datagrams (docs/protocol.md "IQ replay", ADR 0009) -> {Q_u8, I_u8} samples for ddc_top.
//
// In: udp_rx's payload stream, one datagram per tlast, tuser on tlast = truncated. A datagram is
//   bytes 0..SEQ_BYTES-1: u64 big-endian seq;   then SAMPLES x (I_u8, Q_u8).
// Samples are written into a block-RAM ring as they arrive but released to m_* only when the datagram ends well
// (exactly SEQ_BYTES + 2*SAMPLES bytes, tuser low). Otherwise the write pointer rewinds and the DDC never sees any
// of it. So the DDC gets whole datagrams only, and every sample index stays seq * SAMPLES.
//
// Counters (cumulative since reset, mod 2^32), the ingest gap counter of CLAUDE.md §3:
//   ok_cnt_o   datagrams released          bad_cnt_o  datagrams dropped (wrong length or truncated)
//   gap_cnt_o  good datagrams whose seq was not the expected one (the first expected seq is 0)
//   lost_cnt_o sum of forward seq jumps: datagrams missing, so lost samples = SAMPLES * lost_cnt_o
// A repeated or backward seq counts in gap_cnt_o only; its samples are still released.
//
// Backpressure: s_tready drops on a sample's Q byte while the ring is full (DEPTH samples, committed or not). DEPTH >= SAMPLES, so a
// datagram in progress can always finish once the committed samples drain. Upstream, eth_rx counts any frame the
// MII then loses (fpga-eth-core consumer guide), so nothing is dropped silently.
// Output rate: one sample per 3 clocks at most (6.25 MS/s is the 100 Mb/s link's ceiling, 1.024 MS/s real time).
module iq_udp_ingest #(
    parameter int SAMPLES   = 512,   // samples per datagram, docs/protocol.md
    parameter int SEQ_BYTES = 8,     // u64 sequence number, docs/protocol.md
    parameter int DEPTH     = 1024   // ring size in samples, power of two; 1024 x 16 bits = one RAMB18
) (
    input  wire logic        clk_i,
    input  wire logic        rst_i,

    input  wire logic [7:0]  s_tdata_i,
    input  wire logic        s_tvalid_i,
    output      logic        s_tready_o,
    input  wire logic        s_tlast_i,
    input  wire logic        s_tuser_i,   // on tlast: datagram truncated

    output      logic [15:0] m_tdata_o,   // {Q_u8, I_u8}
    output      logic        m_tvalid_o,
    input  wire logic        m_tready_i,

    output      logic [31:0] ok_cnt_o,
    output      logic [31:0] bad_cnt_o,
    output      logic [31:0] gap_cnt_o,
    output      logic [31:0] lost_cnt_o
);

    localparam int AW       = $clog2(DEPTH);
    localparam int LEN      = SEQ_BYTES + 2 * SAMPLES;  // 1,032 bytes, docs/protocol.md
    localparam int IW       = $clog2(LEN + 1) + 1;      // byte index, saturating above LEN
    localparam int SEQ_W    = 8 * SEQ_BYTES;

    if (DEPTH != (1 << AW) || DEPTH < SAMPLES) begin : g_bad_depth
        $error("DEPTH must be a power of two >= SAMPLES");  // elaboration-time check
    end

    (* ram_style = "block" *) logic [15:0] ring_q [DEPTH];

    logic [AW:0]      wr_q, commit_q, rd_q;  // one extra bit: full vs. empty
    logic [IW-1:0]    idx_q;                 // bytes of the current datagram so far, saturating
    logic [SEQ_W-1:0] seq_q, expect_q;
    logic [7:0]       i_byte_q;
    logic             rd_pend_q, out_valid_q;
    logic [15:0]      rd_data_q;

    logic             beat, q_byte, sample_beat, good, full;
    logic [AW:0]      wr_d;

    assign full        = (wr_q - rd_q) == (AW + 1)'(DEPTH);
    // Byte idx is a Q byte when idx - SEQ_BYTES is odd; only the first SAMPLES pairs are stored.
    assign q_byte      = idx_q >= IW'(SEQ_BYTES) && idx_q < IW'(LEN) && idx_q[0] != SEQ_BYTES[0];
    // Only a byte that writes a sample waits for room. Every other byte, in particular the extra bytes and tlast of
    // an over-long datagram after its SAMPLES samples filled the ring, is taken, so the rewind can always happen.
    assign s_tready_o  = !(full && q_byte);
    assign beat        = s_tvalid_i && s_tready_o;
    assign sample_beat = beat && q_byte;
    assign wr_d        = wr_q + (AW + 1)'(sample_beat);
    assign good        = !s_tuser_i && idx_q == IW'(LEN - 1);

    always_ff @(posedge clk_i) begin
        if (sample_beat) ring_q[wr_q[AW-1:0]] <= {s_tdata_i, i_byte_q};
        if (beat) begin
            if (idx_q < IW'(SEQ_BYTES)) seq_q <= {seq_q[SEQ_W-9:0], s_tdata_i};
            i_byte_q <= s_tdata_i;
        end
        if (!rd_pend_q && !out_valid_q && commit_q != rd_q) rd_data_q <= ring_q[rd_q[AW-1:0]];
    end

    always_ff @(posedge clk_i) begin
        if (rst_i) begin
            wr_q        <= '0;
            commit_q    <= '0;
            rd_q        <= '0;
            idx_q       <= '0;
            expect_q    <= '0;
            rd_pend_q   <= 1'b0;
            out_valid_q <= 1'b0;
            ok_cnt_o    <= '0;
            bad_cnt_o   <= '0;
            gap_cnt_o   <= '0;
            lost_cnt_o  <= '0;
        end else begin
            wr_q <= wr_d;
            if (beat) begin
                if (s_tlast_i) begin
                    idx_q <= '0;
                    if (good) begin
                        commit_q <= wr_d;
                        ok_cnt_o <= ok_cnt_o + 32'd1;
                        expect_q <= seq_q + SEQ_W'(1);
                        if (seq_q != expect_q) begin
                            gap_cnt_o <= gap_cnt_o + 32'd1;
                            if (seq_q > expect_q) lost_cnt_o <= lost_cnt_o + 32'(seq_q - expect_q);
                        end
                    end else begin
                        wr_q      <= commit_q;  // rewind: none of this datagram is released
                        bad_cnt_o <= bad_cnt_o + 32'd1;
                    end
                end else if (idx_q != '1) begin
                    idx_q <= idx_q + IW'(1);
                end
            end

            // Read side: one BRAM read in flight at a time, then hold the word until it is taken.
            if (!rd_pend_q && !out_valid_q && commit_q != rd_q) begin
                rd_q      <= rd_q + (AW + 1)'(1);
                rd_pend_q <= 1'b1;
            end else if (rd_pend_q) begin
                rd_pend_q   <= 1'b0;
                out_valid_q <= 1'b1;
            end else if (out_valid_q && m_tready_i) begin
                out_valid_q <= 1'b0;
            end
        end
    end

    assign m_tdata_o  = rd_data_q;
    assign m_tvalid_o = out_valid_q;

`ifndef SYNTHESIS
    // Never more than DEPTH samples in the ring; the reader stays behind the committed pointer.
    a_ring_bounds: assert property (@(posedge clk_i) disable iff (rst_i)
        (wr_q - rd_q) <= (AW + 1)'(DEPTH) && (commit_q - rd_q) <= (wr_q - rd_q))
        else $error("ring pointers wr=%0d commit=%0d rd=%0d", wr_q, commit_q, rd_q);
    // An uncommitted datagram never holds more than SAMPLES samples.
    a_uncommitted: assert property (@(posedge clk_i) disable iff (rst_i) (wr_q - commit_q) <= (AW + 1)'(SAMPLES));
    // AXI-Stream: data held stable while valid and not taken.
    a_hold: assert property (@(posedge clk_i) disable iff (rst_i)
        m_tvalid_o && !m_tready_i |=> m_tvalid_o && $stable(m_tdata_o));
`endif

endmodule

`default_nettype wire
