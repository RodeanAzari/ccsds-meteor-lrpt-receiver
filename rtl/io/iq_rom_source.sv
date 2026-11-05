`default_nettype none

// Plays a cu8 I/Q snippet from a block-RAM ROM once after reset, as an AXI-Stream source (Phase B bring-up without
// Ethernet: fpga-coord gate eth-core-v0.1 "until then: short IQ snippets in a BRAM ROM").
// m_tdata = {Q_u8, I_u8} (ddc_ingest's input). The ROM read is registered (one BRAM read stage); a read is issued only
// when the output register will be free the next cycle, so the stream honours backpressure. At most one sample every
// two cycles: ample, since the DDC takes one every nine (data/results/ddc_rtl_sim.csv).
module iq_rom_source #(
    parameter int    N_SAMPLES = 65536,          // ROM depth in samples
    parameter string ROM_FILE  = "iq_rom.mem"    // one 16-bit hex word per line, {Q_u8, I_u8}
) (
    input  wire logic        clk_i,
    input  wire logic        rst_i,
    output      logic [15:0] m_tdata_o,
    output      logic        m_tvalid_o,
    input  wire logic        m_tready_i,
    output      logic        done_o       // every sample has been accepted
);

    localparam int AW = $clog2(N_SAMPLES);

    (* rom_style = "block" *) logic [15:0] rom [N_SAMPLES];
    initial $readmemh(ROM_FILE, rom);

    logic [AW:0] rd_addr_q;   // next address to read
    logic [AW:0] sent_q;      // samples accepted downstream
    logic        rd_vld_q;    // a read was issued last cycle; its data is in rd_data_q
    logic [15:0] rd_data_q;
    logic        can_read;

    // Read when the output stage will be free next cycle: empty, or emptied now and no read in flight.
    assign can_read = rd_addr_q < (AW+1)'(N_SAMPLES) && !rd_vld_q && (!m_tvalid_o || m_tready_i);

    always_ff @(posedge clk_i) begin
        if (can_read) rd_data_q <= rom[rd_addr_q[AW-1:0]];
    end

    always_ff @(posedge clk_i) begin
        if (rst_i) begin
            rd_addr_q  <= '0;
            sent_q     <= '0;
            rd_vld_q   <= 1'b0;
            m_tvalid_o <= 1'b0;
        end else begin
            rd_vld_q <= can_read;
            if (can_read) rd_addr_q <= rd_addr_q + 1'b1;
            if (m_tvalid_o && m_tready_i) sent_q <= sent_q + 1'b1;
            if (rd_vld_q) begin
                m_tdata_o  <= rd_data_q;
                m_tvalid_o <= 1'b1;
            end else if (m_tready_i) begin
                m_tvalid_o <= 1'b0;
            end
        end
    end

    assign done_o = sent_q == (AW+1)'(N_SAMPLES);

endmodule

`default_nettype wire
