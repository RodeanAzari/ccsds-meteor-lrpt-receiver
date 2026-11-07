`default_nettype none

// Phase B on hardware, fed over Ethernet (buildplan §9 Phase B: "then over Ethernet from gs-replay"):
//
//   gs-replay -> 100 Mb/s MII -> eth_rx -> udp_rx (fpga-eth-core, rtl/eth at its tag) -> iq_udp_ingest
//             -> ddc_top -> capture_dump (BRAM) -> uart_tx -> USB-UART -> host
//
// Same DDC, capture and dump format as arty_ddc_rom_top, so scripts/ddc_board.py checks it the same way: the
// first N_OUT DDC outputs after reset, i.e. the first 4 * N_OUT samples of the replay (datagrams 0..4N_OUT/512-1).
// Replay to a freshly reset board (RESET button): the DDC's state and the expected seq start from zero.
// BTN0 sends the capture again.
//
// Ingest and link errors (iq_udp_ingest bad/gap counters; eth_rx CRC, rx_er, overflow; udp_rx checksum and
// malformed) light LD7 until reset. The counters go back to the host with the Phase E stats packet
// (docs/protocol.md); here, a bit-exact capture already proves its datagrams arrived whole and in order.
// LEDs: LD4 heartbeat, LD5 capture full, LD6 dumping, LD7 sticky error.
//
// Clocks: one 100 MHz core domain from the MMCM (clk_gen_eth) for everything after eth_rx's FIFO, plus the
// PHY's 25 MHz rx_clk inside eth_rx. Start-up per the fpga-eth-core consumer guide: PHY reset released 10 ms,
// MAC 200 ms after the MMCM locks. The transmit pins are idle (Phase E uses them); MDIO is unused (PHY straps).
module arty_ddc_eth_top #(
    parameter int          N_OUT            = 16384,         // DDC outputs captured = 65,536 samples / 4
    parameter logic [31:0] FREQ_WORD        = 32'h2580_0000, // 150 kHz at 1.024 MS/s = 600 * 2^20 (ADR 0003)
    parameter int          CLKS_PER_BIT     = 868,           // 115,200 baud at 100 MHz
    parameter int          PHY_RST_CYCLES   = 1_000_000,     // 10 ms at 100 MHz, fpga-eth-core consumer guide
    parameter int          MAC_START_CYCLES = 20_000_000,    // 200 ms at 100 MHz, same
    parameter logic [47:0] OWN_MAC          = 48'h02_00_0A_0B_0C_0D,  // locally administered; unused for multicast
    parameter logic [31:0] GROUP_IP         = 32'hEF_01_01_01,        // 239.1.1.1, docs/protocol.md
    parameter logic [15:0] UDP_PORT         = 16'd26400,              // docs/protocol.md
    parameter string       NCO_LUT_FILE     = "nco_lut.mem",
    parameter string       COMP_TAP_FILE    = "comp_fir_taps.mem"
) (
    input  wire logic       clk100_i,      // E3, 100 MHz oscillator
    input  wire logic       ck_rst_n_i,    // C2, RESET button, active-low
    input  wire logic       btn0_i,        // D9, BTN0
    output      logic       uart_txd_o,    // D10, FPGA -> host
    output      logic [3:0] led_o,
    // Ethernet PHY (TI DP83848J, MII)
    output      logic       eth_ref_clk_o,
    output      logic       eth_rstn_o,
    input  wire logic       eth_rx_clk_i,
    input  wire logic       eth_rx_dv_i,
    input  wire logic [3:0] eth_rxd_i,
    input  wire logic       eth_rxerr_i,
    output      logic       eth_tx_en_o,
    output      logic [3:0] eth_txd_o,
    output      logic       eth_mdc_o
);

    localparam int START_W = $clog2(MAC_START_CYCLES + 1);

    // ------------------------------------------------------------------------------------ clocks and resets
    logic clk, locked, rst, mii_rst;

    clk_gen_eth u_clk (
        .clk100_i      (clk100_i),
        .clk_core_o    (clk),
        .eth_ref_clk_o (eth_ref_clk_o),
        .locked_o      (locked)
    );

    reset_sync u_rst_core (
        .clk_i       (clk),
        .rst_async_i (!ck_rst_n_i || !locked),
        .rst_o       (rst)
    );

    logic [START_W-1:0] start_q;
    // mac_rst_q is the core domain's synchronous MAC reset and, by design, the asynchronous reset request into the
    // rx_clk domain's reset_sync (the consumer guide: both domains leave reset from one source).
    /* verilator lint_off SYNCASYNCNET */
    logic               mac_rst_q;
    /* verilator lint_on SYNCASYNCNET */

    always_ff @(posedge clk) begin
        if (rst) begin
            start_q    <= '0;
            eth_rstn_o <= 1'b0;
            mac_rst_q  <= 1'b1;
        end else begin
            if (start_q != START_W'(MAC_START_CYCLES)) start_q <= start_q + START_W'(1);
            eth_rstn_o <= start_q >= START_W'(PHY_RST_CYCLES);
            mac_rst_q  <= start_q != START_W'(MAC_START_CYCLES);
        end
    end

    reset_sync u_rst_mii (
        .clk_i       (eth_rx_clk_i),
        .rst_async_i (mac_rst_q),
        .rst_o       (mii_rst)
    );

    assign eth_tx_en_o = 1'b0;
    assign eth_txd_o   = 4'd0;
    assign eth_mdc_o   = 1'b0;

    // -------------------------------------------------------------------------------------- receive path
    logic [7:0] f_tdata;
    logic       f_tvalid, f_tready, f_tlast;
    logic       e_ok, e_crc, e_rxerr, e_runt, e_over, e_ovf;
    logic [7:0] e_ovf_frames;
    logic [11:0] fifo_level;
    logic       sfd;

    eth_rx #(
        .FIFO_ADDR_W (11)  // 2 KB, the fpga-eth-core examples' size
    ) u_eth_rx (
        .mii_clk_i    (eth_rx_clk_i),
        .mii_rst_i    (mii_rst),
        .mii_rxd_i    (eth_rxd_i),
        .mii_rx_dv_i  (eth_rx_dv_i),
        .mii_rx_er_i  (eth_rxerr_i),
        .sfd_o        (sfd),
        .clk_i        (clk),
        .rst_i        (mac_rst_q),
        .m_tdata_o    (f_tdata),
        .m_tvalid_o   (f_tvalid),
        .m_tready_i   (f_tready),
        .m_tlast_o    (f_tlast),
        .frame_ok_o   (e_ok),
        .crc_err_o    (e_crc),
        .rx_err_o     (e_rxerr),
        .runt_o       (e_runt),
        .oversize_o   (e_over),
        .ovf_o        (e_ovf),
        .ovf_frames_o (e_ovf_frames),
        .fifo_level_o (fifo_level)
    );

    logic [7:0]  u_tdata;
    logic        u_tvalid, u_tready, u_tlast, u_tuser;
    logic        u_ok, u_filt, u_csum, u_mal;
    logic [47:0] src_mac;
    logic [31:0] src_ip;
    logic [15:0] src_port, dst_port;

    udp_rx u_udp_rx (
        .clk_i         (clk),
        .rst_i         (mac_rst_q),
        .cfg_mac_i     (OWN_MAC),
        .cfg_ip_i      (GROUP_IP),
        .cfg_port_i    (UDP_PORT),
        .s_tdata_i     (f_tdata),
        .s_tvalid_i    (f_tvalid),
        .s_tready_o    (f_tready),
        .s_tlast_i     (f_tlast),
        .m_tdata_o     (u_tdata),
        .m_tvalid_o    (u_tvalid),
        .m_tready_i    (u_tready),
        .m_tlast_o     (u_tlast),
        .m_tuser_o     (u_tuser),
        .src_mac_o     (src_mac),
        .src_ip_o      (src_ip),
        .src_port_o    (src_port),
        .dst_port_o    (dst_port),
        .ok_o          (u_ok),
        .filtered_o    (u_filt),
        .ip_csum_err_o (u_csum),
        .malformed_o   (u_mal)
    );

    logic [15:0] iq_tdata;
    logic        iq_tvalid, iq_tready;
    logic [31:0] ok_cnt, bad_cnt, gap_cnt, lost_cnt;

    iq_udp_ingest u_ingest (
        .clk_i      (clk),
        .rst_i      (mac_rst_q),
        .s_tdata_i  (u_tdata),
        .s_tvalid_i (u_tvalid),
        .s_tready_o (u_tready),
        .s_tlast_i  (u_tlast),
        .s_tuser_i  (u_tuser),
        .m_tdata_o  (iq_tdata),
        .m_tvalid_o (iq_tvalid),
        .m_tready_i (iq_tready),
        .ok_cnt_o   (ok_cnt),
        .bad_cnt_o  (bad_cnt),
        .gap_cnt_o  (gap_cnt),
        .lost_cnt_o (lost_cnt)
    );

    // ----------------------------------------------------------------------------- DDC, capture, readout
    logic [31:0] bb_tdata;
    logic        bb_tvalid, bb_tready;
    logic [7:0]  tx_tdata;
    logic        tx_tvalid, tx_tready;
    logic        btn0, btn0_q, dump, full, busy;

    ddc_top #(
        .NCO_LUT_FILE  (NCO_LUT_FILE),
        .COMP_TAP_FILE (COMP_TAP_FILE)
    ) u_ddc (
        .clk_i       (clk),
        .rst_i       (mac_rst_q),
        .freq_word_i (FREQ_WORD),
        .s_tdata_i   (iq_tdata),
        .s_tvalid_i  (iq_tvalid),
        .s_tready_o  (iq_tready),
        .m_tdata_o   (bb_tdata),
        .m_tvalid_o  (bb_tvalid),
        .m_tready_i  (bb_tready)
    );

    cdc_sync_bit u_btn0 (
        .clk_i (clk),
        .d_i   (btn0_i),
        .q_o   (btn0)
    );

    // Rising edge of BTN0. Bounces land while the dump is busy, and capture_dump ignores dump_i then.
    always_ff @(posedge clk) btn0_q <= btn0;
    assign dump = btn0 && !btn0_q;

    capture_dump #(
        .N_WORDS (N_OUT)
    ) u_cap (
        .clk_i      (clk),
        .rst_i      (mac_rst_q),
        .s_tdata_i  (bb_tdata),
        .s_tvalid_i (bb_tvalid),
        .s_tready_o (bb_tready),
        .dump_i     (dump),
        .full_o     (full),
        .busy_o     (busy),
        .m_tdata_o  (tx_tdata),
        .m_tvalid_o (tx_tvalid),
        .m_tready_i (tx_tready)
    );

    uart_tx #(
        .CLKS_PER_BIT (CLKS_PER_BIT)
    ) u_tx (
        .clk_i      (clk),
        .rst_i      (rst),
        .s_tdata_i  (tx_tdata),
        .s_tvalid_i (tx_tvalid),
        .s_tready_o (tx_tready),
        .txd_o      (uart_txd_o)
    );

    // ------------------------------------------------------------------------------------------ status
    // Runts and oversize frames are not counted: other hosts' traffic on the cable can produce them.
    // Datagrams for other groups/ports (u_filt) are not errors either.
    logic err_q;
    logic [26:0] beat_q;

    always_ff @(posedge clk) begin
        if (mac_rst_q) err_q <= 1'b0;
        else if (e_crc || e_rxerr || e_ovf || u_csum || u_mal || bad_cnt != '0 || gap_cnt != '0) err_q <= 1'b1;
    end

    always_ff @(posedge clk) begin
        if (rst) beat_q <= '0;
        else     beat_q <= beat_q + 1'b1;
    end

    assign led_o = {err_q, busy, full, beat_q[26]};

    // Unused outputs, kept visible for the ILA and the Phase E stats packet.
    logic unused;
    assign unused = ^{sfd, e_ok, e_runt, e_over, e_ovf_frames, fifo_level, u_ok, u_filt, src_mac, src_ip,
                      src_port, dst_port, ok_cnt, lost_cnt};

endmodule

`default_nettype wire
