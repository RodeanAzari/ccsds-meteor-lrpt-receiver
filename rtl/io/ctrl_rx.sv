`default_nettype none

// Control commands (docs/protocol.md "Control commands", ADR 0014), read off the replay datagram stream.
//
// Snoops udp_rx's payload stream as the ingest takes it (beat = tvalid && tready, one datagram per tlast, tuser on
// tlast = truncated); it never stalls the stream. A datagram whose byte 0 has bit 7 set is a command, not replay
// data (iq_udp_ingest ignores it). The only command, SET_NCO, is exactly 8 bytes:
//   bytes 0-3: u32 big-endian CMD_SET_NCO;   bytes 4-7: u32 big-endian DDC NCO word (f / fs * 2^32).
// It is accepted only while lock_i is low (the DDC has not taken a sample since reset: ADR 0014, so every sample
// of a replay sees one word). Accepting pulses set_o for one clock with word_o valid, combinationally on the
// command's last beat, so a word accepted on a clock where lock_i is low is in place for the DDC's next sample.
//
// Counters (cumulative since reset, mod 2^32):
//   ok_cnt_o   commands accepted
//   bad_cnt_o  command datagrams refused: wrong length, truncated, unknown command, or SET_NCO while locked
module ctrl_rx (
    input  wire logic        clk_i,
    input  wire logic        rst_i,

    input  wire logic [7:0]  s_tdata_i,
    input  wire logic        s_beat_i,    // s_tvalid && s_tready of the snooped stream
    input  wire logic        s_tlast_i,
    input  wire logic        s_tuser_i,   // on tlast: datagram truncated

    input  wire logic        lock_i,      // high: SET_NCO refused

    output      logic        set_o,
    output      logic [31:0] word_o,

    output      logic [31:0] ok_cnt_o,
    output      logic [31:0] bad_cnt_o
);

    localparam int          LEN         = 8;              // docs/protocol.md "Control commands"
    localparam logic [31:0] CMD_SET_NCO = 32'h8000_0001;  // docs/protocol.md "Control commands"

    logic [3:0]  idx_q;    // bytes of the current datagram so far, saturating at 15 (> LEN)
    logic [55:0] sh_q;     // its first 7 bytes, byte 0 highest
    logic        ctrl_q;   // its byte 0 had bit 7 set
    logic        ctrl, good;

    assign ctrl   = idx_q == '0 ? s_tdata_i[7] : ctrl_q;
    assign good   = idx_q == 4'(LEN - 1) && !s_tuser_i && sh_q[55:24] == CMD_SET_NCO;
    assign word_o = {sh_q[23:0], s_tdata_i};
    assign set_o  = s_beat_i && s_tlast_i && ctrl && good && !lock_i;

    always_ff @(posedge clk_i) begin
        if (s_beat_i) begin
            if (idx_q == '0) ctrl_q <= s_tdata_i[7];
            sh_q <= {sh_q[47:0], s_tdata_i};
        end
    end

    always_ff @(posedge clk_i) begin
        if (rst_i) begin
            idx_q     <= '0;
            ok_cnt_o  <= '0;
            bad_cnt_o <= '0;
        end else if (s_beat_i) begin
            if (s_tlast_i) begin
                idx_q <= '0;
                if (set_o)     ok_cnt_o  <= ok_cnt_o + 32'd1;
                else if (ctrl) bad_cnt_o <= bad_cnt_o + 32'd1;
            end else if (idx_q != '1) begin
                idx_q <= idx_q + 4'd1;
            end
        end
    end

endmodule

`default_nettype wire
