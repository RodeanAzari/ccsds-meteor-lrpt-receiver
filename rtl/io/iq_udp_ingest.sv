`default_nettype none

// IQ replay datagrams (docs/protocol.md "IQ replay", ADRs 0009, 0011, 0013) -> {Q_u8, I_u8} samples for ddc_top.
//
// In: udp_rx's payload stream, one datagram per tlast, tuser on tlast = truncated. A datagram is
//   bytes 0..SEQ_BYTES-1: u64 big-endian seq;   then SAMPLES x (I_u8, Q_u8).
//
// Reorder buffer (ADR 0013): the block-RAM ring holds NSLOT = DEPTH / SAMPLES slots of one datagram each; datagram
// seq lives in slot seq mod NSLOT. head_q is the next seq to release. A good datagram (exactly SEQ_BYTES +
// 2*SAMPLES bytes, tuser low) with head <= seq < head + NSLOT is written into its slot and marks it valid; the
// reader releases valid slots strictly in seq order from head. So datagrams swapped within the window reach the DDC
// in file order, the DDC still gets whole datagrams only, and every sample index stays seq * SAMPLES (minus the
// samples of datagrams lost: those are not filled in).
//   - seq >= head + NSLOT (detected at the datagram's first sample byte, which waits): the head is released if valid,
//     or skipped as lost if not, until the datagram fits the window.
//   - seq < head, or its slot already valid (a duplicate): late, consumed and dropped.
//   - bad datagrams: their slot is not marked; the next good datagram for it overwrites what they wrote.
// A datagram lost at the end of a replay holds the ones after it until a datagram NSLOT further on arrives.
// Control commands (byte 0 bit 7 set, docs/protocol.md "Control commands", ADR 0014) are not replay data: consumed
// without a write, a window move or a count (ctrl_rx counts them).
//
// Counters (cumulative since reset, mod 2^32), the ingest gap counter of CLAUDE.md §3:
//   ok_cnt_o   good datagrams placed for release          bad_cnt_o   dropped: wrong length or truncated
//   gap_cnt_o  placed datagrams whose seq was not the previous placed seq + 1 (the first expected is 0): arrival
//              out of order, or after a loss
//   lost_cnt_o datagrams skipped because they had not arrived when the window had to move: SAMPLES samples each
//   late_cnt_o good datagrams dropped: behind the window, or duplicates
//
// Backpressure: only a datagram beyond the window waits (on its first sample byte) while the head slot drains;
// everything else is taken at once. Upstream, eth_rx counts any frame the MII then loses (fpga-eth-core consumer
// guide), so nothing is dropped silently.
// Output rate: one sample per 3 clocks at most (6.25 MS/s is the 100 Mb/s link's ceiling, 1.024 MS/s real time).
module iq_udp_ingest #(
    parameter int SAMPLES   = 512,   // samples per datagram, docs/protocol.md
    parameter int SEQ_BYTES = 8,     // u64 sequence number, docs/protocol.md
    parameter int DEPTH     = 2048   // ring size in samples, a power-of-two multiple of SAMPLES (ADR 0013: 4 slots)
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
    output      logic [31:0] lost_cnt_o,
    output      logic [31:0] late_cnt_o
);

    localparam int AW     = $clog2(DEPTH);
    localparam int SW     = $clog2(SAMPLES);            // sample index within a slot
    localparam int NSLOT  = DEPTH / SAMPLES;
    localparam int NW     = AW - SW;                    // slot index bits (0 when NSLOT = 1)
    localparam int LEN    = SEQ_BYTES + 2 * SAMPLES;    // 1,032 bytes, docs/protocol.md
    localparam int IW     = $clog2(LEN + 1) + 1;        // byte index, saturating above LEN
    localparam int SEQ_W  = 8 * SEQ_BYTES;

    if (SAMPLES != (1 << SW) || DEPTH != (1 << AW) || NSLOT < 1 || DEPTH % SAMPLES != 0) begin : g_bad_depth
        $error("SAMPLES and DEPTH must be powers of two, DEPTH >= SAMPLES");  // elaboration-time check
    end

    (* ram_style = "block" *) logic [15:0] ring_q [DEPTH];

    logic [IW-1:0]    idx_q;                  // bytes of the current datagram so far, saturating
    logic [SEQ_W-1:0] seq_q;                  // the current datagram's seq (complete from byte SEQ_BYTES on)
    logic [SEQ_W-1:0] head_q;                 // next seq to release
    logic [SEQ_W-1:0] next_q;                 // previous placed seq + 1 (gap counting)
    logic [NSLOT-1:0] valid_q;                // slot holds a good datagram not yet fully released
    logic             drop_q;                 // current datagram is late, a duplicate or a command: no write, no place
    logic             ctrl_q;                 // current datagram is a control command (its byte 0 bit 7 was set)
    logic [7:0]       i_byte_q;
    logic [SW-1:0]    rd_idx_q;               // next sample of the head slot to read
    logic             rd_pend_q, out_valid_q;
    logic [15:0]      rd_data_q;

    logic             beat, q_byte, first_sample, sample_beat, good, far, late, seq_valid, head_valid, rd_go, rd_last;
    logic             place, ctrl;
    logic [SEQ_W-1:0] ahead;
    logic [SW-1:0]    wr_k;
    logic [AW-1:0]    wr_addr, rd_addr;
    logic [NSLOT-1:0] seq_oh, head_oh;        // one-hot slot of seq_q / head_q

    // Slot of a seq: its low NW bits (NSLOT is a power of two). With one slot every seq maps to slot 0.
    if (NW == 0) begin : g_one_slot
        assign wr_addr = AW'(wr_k);
        assign rd_addr = AW'(rd_idx_q);
        assign seq_oh  = 1'b1;
        assign head_oh = 1'b1;
    end else begin : g_slots
        assign wr_addr = {seq_q[NW-1:0], wr_k};
        assign rd_addr = {head_q[NW-1:0], rd_idx_q};
        assign seq_oh  = NSLOT'(1) << seq_q[NW-1:0];
        assign head_oh = NSLOT'(1) << head_q[NW-1:0];
    end

    assign seq_valid    = (valid_q & seq_oh) != '0;
    assign head_valid   = (valid_q & head_oh) != '0;
    assign ahead        = seq_q - head_q;
    assign far          = seq_q >= head_q && ahead >= SEQ_W'(NSLOT) && !ctrl_q;
    assign ctrl         = idx_q == '0 ? s_tdata_i[7] : ctrl_q;  // on byte 0 itself, from the byte
    assign late         = seq_q < head_q || seq_valid;
    // Byte idx is a Q byte when idx - SEQ_BYTES is odd; only the first SAMPLES pairs are stored.
    assign q_byte       = idx_q >= IW'(SEQ_BYTES) && idx_q < IW'(LEN) && idx_q[0] != SEQ_BYTES[0];
    assign first_sample = idx_q == IW'(SEQ_BYTES);
    // The first sample byte of a datagram beyond the window waits until the window has moved up to it.
    assign s_tready_o   = !(first_sample && far);
    assign beat         = s_tvalid_i && s_tready_o;
    assign sample_beat  = beat && q_byte && !drop_q;
    assign good         = !s_tuser_i && idx_q == IW'(LEN - 1);
    assign wr_k         = SW'((idx_q - IW'(SEQ_BYTES)) >> 1);
    assign place        = beat && s_tlast_i && good && !drop_q;
    assign rd_go        = !rd_pend_q && !out_valid_q && head_valid;
    assign rd_last      = rd_idx_q == SW'(SAMPLES - 1);

    always_ff @(posedge clk_i) begin
        if (sample_beat) ring_q[wr_addr] <= {s_tdata_i, i_byte_q};
        if (beat) begin
            if (idx_q < IW'(SEQ_BYTES)) seq_q <= {seq_q[SEQ_W-9:0], s_tdata_i};
            if (idx_q == '0) ctrl_q <= s_tdata_i[7];
            i_byte_q <= s_tdata_i;
        end
        if (rd_go) rd_data_q <= ring_q[rd_addr];
    end

    always_ff @(posedge clk_i) begin
        if (rst_i) begin
            idx_q       <= '0;
            head_q      <= '0;
            next_q      <= '0;
            valid_q     <= '0;
            drop_q      <= 1'b0;
            rd_idx_q    <= '0;
            rd_pend_q   <= 1'b0;
            out_valid_q <= 1'b0;
            ok_cnt_o    <= '0;
            bad_cnt_o   <= '0;
            gap_cnt_o   <= '0;
            lost_cnt_o  <= '0;
            late_cnt_o  <= '0;
        end else begin
            // Window move for a datagram beyond it: skip the head while it is missing (a valid head is released by
            // the reader below, which moves head_q itself). Never in the same cycle as a read of the head slot.
            if (first_sample && s_tvalid_i && far && !head_valid && !rd_pend_q && !out_valid_q) begin
                head_q     <= head_q + SEQ_W'(1);
                lost_cnt_o <= lost_cnt_o + 32'd1;
            end

            if (beat) begin
                if (first_sample) drop_q <= late || ctrl_q;  // decided once, on the first sample byte (seq complete)
                if (s_tlast_i) begin
                    idx_q  <= '0;
                    drop_q <= 1'b0;
                    if (ctrl) begin
                        // a command: ctrl_rx's
                    end else if (!good) begin
                        bad_cnt_o <= bad_cnt_o + 32'd1;
                    end else if (drop_q) begin
                        late_cnt_o <= late_cnt_o + 32'd1;
                    end else begin
                        ok_cnt_o <= ok_cnt_o + 32'd1;
                        next_q   <= seq_q + SEQ_W'(1);
                        if (seq_q != next_q) gap_cnt_o <= gap_cnt_o + 32'd1;
                    end
                end else if (idx_q != '1) begin
                    idx_q <= idx_q + IW'(1);
                end
            end

            // Read side: one BRAM read in flight at a time, then hold the word until it is taken. After the head
            // slot's last sample is read, the slot is free and the window moves on.
            if (rd_go) begin
                rd_pend_q <= 1'b1;
                rd_idx_q  <= rd_idx_q + SW'(1);
                if (rd_last) head_q <= head_q + SEQ_W'(1);
            end else if (rd_pend_q) begin
                rd_pend_q   <= 1'b0;
                out_valid_q <= 1'b1;
            end else if (out_valid_q && m_tready_i) begin
                out_valid_q <= 1'b0;
            end

            // Placed slots become valid; the head slot frees once its last sample is read. Never the same slot: a
            // datagram is only placed into a slot that is not valid, and only a valid slot is read.
            valid_q <= (valid_q | (place ? seq_oh : '0)) & ~(rd_go && rd_last ? head_oh : '0);
        end
    end

    assign m_tdata_o  = rd_data_q;
    assign m_tvalid_o = out_valid_q;

`ifndef SYNTHESIS
    // A sample is only ever written into a slot that is not waiting for release.
    a_write_free: assert property (@(posedge clk_i) disable iff (rst_i) sample_beat |-> !seq_valid);
    // The current datagram, once placed, lies inside the window.
    a_in_window: assert property (@(posedge clk_i) disable iff (rst_i)
        sample_beat |-> seq_q >= head_q && ahead < SEQ_W'(NSLOT));
    // AXI-Stream: data held stable while valid and not taken.
    a_hold: assert property (@(posedge clk_i) disable iff (rst_i)
        m_tvalid_o && !m_tready_i |=> m_tvalid_o && $stable(m_tdata_o));
`endif

endmodule

`default_nettype wire
