`default_nettype none

// CADU packet (docs/protocol.md "Board → host packets" and "CADU", type 2) as a UDP payload byte stream for
// fpga-eth-core's udp_tx: per CADU from fec_cadu,
//   type | version | n = 1,032 | pkt_seq (u32) | uptime (u64) | flags | asm_errors | rs[0..3] | 0, 0 | 1,024 bytes
// all big-endian. The 24 header and status bytes are captured into a shift register on the CADU's first byte
// (status from its tuser, constant over the CADU), then the CADU's bytes pass straight through. Nothing is dropped:
// while enable_i is low (no destination known yet) the CADU waits, and so does the chain behind it.
module cadu_packet #(
    parameter logic [7:0] TYPE    = 8'd2,  // docs/protocol.md: 2 = CADU
    parameter logic [7:0] VERSION = 8'd1,  // docs/protocol.md
    parameter int         CADU    = 1024   // model/coding.py CADU_BYTES
) (
    input  wire logic        clk_i,
    input  wire logic        rst_i,
    input  wire logic        enable_i,

    input  wire logic [7:0]  s_tdata_i,   // fec_cadu m_*
    input  wire logic [32:0] s_tuser_i,
    input  wire logic        s_tlast_i,
    input  wire logic        s_tvalid_i,
    output      logic        s_tready_o,

    output      logic [7:0]  m_tdata_o,
    output      logic        m_tvalid_o,
    input  wire logic        m_tready_i,
    output      logic        m_tlast_o
);

    localparam int HDR  = 16 + 8;     // common header + CADU status (docs/protocol.md)
    localparam int HW   = $clog2(HDR + 1);
    localparam int N    = 8 + CADU;   // header field n: payload bytes after the common header

    logic [HDR*8-1:0] hdr_q;      // next header byte in the top 8 bits
    logic [HW-1:0]    hdr_left_q; // header bytes still to send
    logic             body_q;     // passing CADU bytes through
    logic [31:0]      seq_q;
    logic [63:0]      uptime_q;
    logic             start;

    // fec_cadu status word (model/cadu_fixed.py): [2:0] {flywheel, swap, alternate}, [8:3] ASM errors,
    // [9+6c +: 6] codeword c {fail, count[4:0]}. Repacked: flags byte, asm byte, rs bytes {fail, 00, count}.
    function automatic logic [7:0] rs_byte(input logic [5:0] f);
        return {f[5], 2'b00, f[4:0]};
    endfunction

    assign start = s_tvalid_i && enable_i && hdr_left_q == '0 && !body_q;

    always_ff @(posedge clk_i) begin
        if (rst_i) begin
            hdr_left_q <= '0;
            body_q     <= 1'b0;
            seq_q      <= '0;
            uptime_q   <= '0;
        end else begin
            uptime_q <= uptime_q + 64'd1;
            if (start) begin
                hdr_q      <= {TYPE, VERSION, 16'(N), seq_q, uptime_q,
                               5'd0, s_tuser_i[2:0], 2'd0, s_tuser_i[8:3],
                               rs_byte(s_tuser_i[14:9]), rs_byte(s_tuser_i[20:15]),
                               rs_byte(s_tuser_i[26:21]), rs_byte(s_tuser_i[32:27]), 16'd0};
                hdr_left_q <= HW'(HDR);
                seq_q      <= seq_q + 32'd1;
            end else if (hdr_left_q != '0 && m_tready_i) begin
                hdr_q      <= hdr_q << 8;
                hdr_left_q <= hdr_left_q - HW'(1);
                if (hdr_left_q == HW'(1)) body_q <= 1'b1;
            end else if (body_q && s_tvalid_i && m_tready_i && s_tlast_i) begin
                body_q <= 1'b0;
            end
        end
    end

    always_comb begin
        if (hdr_left_q != '0) begin
            m_tdata_o  = hdr_q[HDR*8-1 -: 8];
            m_tvalid_o = 1'b1;
            m_tlast_o  = 1'b0;
            s_tready_o = 1'b0;
        end else begin
            m_tdata_o  = s_tdata_i;
            m_tvalid_o = body_q && s_tvalid_i;
            m_tlast_o  = s_tlast_i;
            s_tready_o = body_q && m_tready_i;
        end
    end

`ifndef SYNTHESIS
    // Coverage bins (make cov, docs/coverage.md): backpressure on each interface.
    cov_bp_s: cover property (@(posedge clk_i) disable iff (rst_i) s_tvalid_i && !s_tready_o);
    cov_bp_m: cover property (@(posedge clk_i) disable iff (rst_i) m_tvalid_o && !m_tready_i);
`endif

endmodule

`default_nettype wire
