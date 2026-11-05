`default_nettype none

// Captures N_WORDS 32-bit stream words into block RAM, then sends them as bytes (to uart_tx): once when the buffer
// fills, and again on every dump_i pulse while idle. Phase B bring-up readout until eth-core-v0.2 (fpga-coord).
//
// Byte format, all little-endian:  "DDC1" | u32 N_WORDS | N_WORDS x u32 word | u32 CRC-32.   Parsed by
// scripts/ddc_board.py. The CRC (IEEE/zlib: reflected 0xEDB88320, init and final XOR 0xFFFFFFFF) covers every
// byte before it, so the host can tell a cut-off or corrupted dump from a DDC error: opening the serial port resets
// the board and restarts the dump (docs/log.md), so truncated dumps do occur.
// s_tready drops once the buffer is full, so the stream is held, never dropped.
module capture_dump #(
    parameter int N_WORDS = 16384
) (
    input  wire logic        clk_i,
    input  wire logic        rst_i,

    input  wire logic [31:0] s_tdata_i,
    input  wire logic        s_tvalid_i,
    output      logic        s_tready_o,

    input  wire logic        dump_i,      // one-cycle pulse: send the buffer again
    output      logic        full_o,
    output      logic        busy_o,      // dumping

    output      logic [7:0]  m_tdata_o,   // bytes to uart_tx
    output      logic        m_tvalid_o,
    input  wire logic        m_tready_i
);

    localparam int AW = $clog2(N_WORDS);
    localparam logic [63:0] HEADER = {32'(N_WORDS), "1CDD"};  // sent LSB first: 'D','D','C','1', then N_WORDS

    typedef enum logic [2:0] {IDLE, HDR, FETCH, LOAD, DATA, CRC} state_e;

    (* ram_style = "block" *) logic [31:0] buf_q [N_WORDS];

    logic [AW:0]  wr_q;         // words captured
    logic [AW:0]  rd_q;         // next word to send
    logic [2:0]   byte_q;       // byte index within the header (0..7) or word (0..3)
    logic [31:0]  word_q;       // registered BRAM read
    logic [31:0]  shift_q;      // word being sent
    logic         dumped_q;     // the automatic dump on fill has been done
    logic [31:0]  crc_q;        // running CRC register over the bytes sent so far
    state_e       state_q;

    assign full_o     = wr_q == (AW+1)'(N_WORDS);
    assign s_tready_o = !full_o;
    assign busy_o     = state_q != IDLE;

    always_ff @(posedge clk_i) begin
        if (s_tvalid_i && s_tready_o) buf_q[wr_q[AW-1:0]] <= s_tdata_i;
        word_q <= buf_q[rd_q[AW-1:0]];
    end

    function automatic logic [31:0] crc32_byte(input logic [31:0] c, input logic [7:0] b);
        logic [31:0] r;
        r = c ^ {24'd0, b};
        for (int k = 0; k < 8; k++) r = (r >> 1) ^ (r[0] ? 32'hEDB8_8320 : 32'd0);
        return r;
    endfunction

    always_comb begin
        m_tvalid_o = state_q == HDR || state_q == DATA || state_q == CRC;
        unique case (state_q)
            HDR:     m_tdata_o = HEADER[8*byte_q +: 8];
            CRC:     m_tdata_o = ~crc_q[8*byte_q[1:0] +: 8];
            default: m_tdata_o = shift_q[7:0];
        endcase
    end

    always_ff @(posedge clk_i) begin
        if (rst_i) begin
            wr_q     <= '0;
            rd_q     <= '0;
            byte_q   <= '0;
            dumped_q <= 1'b0;
            state_q  <= IDLE;
        end else begin
            if (s_tvalid_i && s_tready_o) wr_q <= wr_q + 1'b1;
            if (m_tvalid_o && m_tready_i && state_q != CRC) crc_q <= crc32_byte(crc_q, m_tdata_o);
            unique case (state_q)
                IDLE: if (full_o && (!dumped_q || dump_i)) begin
                    dumped_q <= 1'b1;
                    crc_q    <= '1;
                    byte_q   <= '0;
                    rd_q     <= '0;
                    state_q  <= HDR;
                end
                HDR: if (m_tready_i) begin
                    byte_q <= byte_q + 1'b1;
                    if (byte_q == 3'd7) state_q <= FETCH;
                end
                FETCH: state_q <= LOAD;  // rd_q changed on entry; the BRAM read of buf[rd_q] lands in word_q now
                LOAD: begin
                    shift_q <= word_q;
                    byte_q  <= '0;
                    state_q <= DATA;
                end
                DATA: if (m_tready_i) begin
                    shift_q <= shift_q >> 8;
                    byte_q  <= byte_q + 1'b1;
                    if (byte_q == 3'd3) begin
                        rd_q    <= rd_q + 1'b1;
                        byte_q  <= '0;
                        state_q <= rd_q == (AW+1)'(N_WORDS - 1) ? CRC : FETCH;
                    end
                end
                CRC: if (m_tready_i) begin
                    byte_q <= byte_q + 1'b1;
                    if (byte_q == 3'd3) state_q <= IDLE;
                end
            endcase
        end
    end

endmodule

`default_nettype wire
