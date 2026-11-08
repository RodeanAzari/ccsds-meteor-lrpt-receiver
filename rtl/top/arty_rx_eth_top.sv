`default_nettype none

// Phase E on hardware: the whole receiver, fed over Ethernet, CADUs back over Ethernet (buildplan §9 Phase E):
//
//   gs-replay -> 100 Mb/s MII -> eth_rx -> udp_rx (fpga-eth-core, rtl/eth at its tag) -> iq_udp_ingest -> ddc_top
//             -> rx_chain (sync, frame sync, Viterbi, NRZ-M, derandomizer, RS x4) -> cadu_packet --\
//                                                                   stats_packet -> pkt_arb2 -> udp_tx -> eth_tx
//
// Every CADU goes to the host as a type 2 packet (docs/protocol.md "CADU"), stats every STATS_PERIOD as type 1 with
// the receiver's counters appended (fields 18-24), both to the sender of the last good replay datagram, UDP port
// STATS_PORT. Nothing is dropped inside the design: a slow stage stalls the ones before it back to the ingest ring;
// once that is full, eth_rx loses whole frames and counts them (stats eth_ovf_lost), and the replay's seq gaps show
// up in ingest_gap/ingest_lost. Replay to a freshly reset board (RESET button): the chain starts from reset and the
// expected seq from zero.
//
// Tuning: FREQ_WORD is the DDC NCO word with the host's coarse estimate in it (ADR 0002), set per recording at build
// time (scripts/board_rx.py freq-word) until a control path exists (docs/protocol.md "Control commands" [TBD]).
// Loop gains, frame-sync threshold, flywheel and traceback depth: rx_config_pkg, generated from the model.
// LEDs: LD4 heartbeat, LD5 frame sync locked, LD6 toggles per CADU sent, LD7 sticky error.
//
// Clocks and Ethernet start-up as arty_ddc_eth_top (same plumbing, including the request 0005 stopgap).
module arty_rx_eth_top
    import rx_config_pkg::*;
#(
    parameter logic [31:0] FREQ_WORD        = 32'h2580_0000, // 150 kHz, no coarse estimate; set per recording
    parameter int          PHY_RST_CYCLES   = 1_000_000,     // 10 ms at 100 MHz, fpga-eth-core consumer guide
    parameter int          MAC_START_CYCLES = 20_000_000,    // 200 ms at 100 MHz, same
    parameter logic [47:0] OWN_MAC          = 48'h02_00_0A_0B_0C_0D,  // locally administered; unused for multicast
    parameter logic [31:0] GROUP_IP         = 32'hEF_01_01_01,        // 239.1.1.1, docs/protocol.md
    parameter logic [15:0] UDP_PORT         = 16'd26400,              // docs/protocol.md
    parameter logic [31:0] OWN_IP           = 32'hC0_A8_0A_02,        // 192.168.10.2, docs/protocol.md (stats source)
    parameter logic [15:0] STATS_PORT       = 16'd26401,              // docs/protocol.md
    parameter int          STATS_PERIOD     = 10_000_000,             // 100 ms at 100 MHz, docs/protocol.md
    parameter string       NCO_LUT_FILE     = "nco_lut.mem",
    parameter string       COMP_TAP_FILE    = "comp_fir_taps.mem",
    parameter string       RRC_TAP_FILE     = "rrc_taps.mem",     // scripts/gen_rtl_tables.py
    parameter string       PATTERN_FILE     = "asm_patterns.mem"  // scripts/gen_rtl_tables.py
) (
    input  wire logic       clk100_i,      // E3, 100 MHz oscillator
    input  wire logic       ck_rst_n_i,    // C2, RESET button, active-low
    input  wire logic       btn0_i,        // D9, BTN0 (unused)
    output      logic       uart_txd_o,    // D10, idle high (unused)
    output      logic [3:0] led_o,
    // Ethernet PHY (TI DP83848J, MII)
    output      logic       eth_ref_clk_o,
    output      logic       eth_rstn_o,
    input  wire logic       eth_rx_clk_i,
    input  wire logic       eth_rx_dv_i,
    input  wire logic [3:0] eth_rxd_i,
    input  wire logic       eth_rxerr_i,
    input  wire logic       eth_tx_clk_i,
    output      logic       eth_tx_en_o,
    output      logic [3:0] eth_txd_o,
    output      logic       eth_mdc_o
);

    localparam int START_W     = $clog2(MAC_START_CYCLES + 1);
    localparam int FIFO_ADDR_W = 11;  // eth_rx RX FIFO, 2 KB: the fpga-eth-core examples' size

    // ------------------------------------------------------------------------------------ clocks and resets
    logic clk, locked, rst, mii_rst, mii_tx_rst;

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

    // Stopgap for fpga-coord request 0005 (until eth-core holds the MAC in reset until link-up): if the PHY's
    // link-up corrupts eth_rx's RX FIFO, its level reads above the FIFO's depth, which no real fill can reach.
    // Then the MAC alone goes through its reset again (start_q back to PHY_RST_CYCLES: the PHY stays out of reset
    // and keeps its link), and the restart is counted (stats field mac_restarts).
    // Feeds the MAC reset, which is by design the async reset request into the rx/tx_clk domains (see mac_rst_q).
    /* verilator lint_off SYNCASYNCNET */
    logic [11:0] fifo_level /*verilator forceable*/;  // forced by test_arty_ddc_eth_top.py
    /* verilator lint_on SYNCASYNCNET */
    logic        fifo_corrupt;
    logic [31:0] mac_restarts_q;
    // Only while the MAC runs (start_q at its end state): the restart moves start_q away at once, so one event
    // counts once even though mac_rst_q follows a cycle later and the bad level persists until the reset lands.
    assign fifo_corrupt = start_q == START_W'(MAC_START_CYCLES) && !mac_rst_q && fifo_level > 12'(1 << FIFO_ADDR_W);

    always_ff @(posedge clk) begin
        if (rst) begin
            start_q        <= '0;
            eth_rstn_o     <= 1'b0;
            mac_rst_q      <= 1'b1;
            mac_restarts_q <= '0;
        end else begin
            if (fifo_corrupt) begin
                start_q        <= START_W'(PHY_RST_CYCLES);
                mac_restarts_q <= mac_restarts_q + 32'd1;
            end else if (start_q != START_W'(MAC_START_CYCLES)) begin
                start_q <= start_q + START_W'(1);
            end
            eth_rstn_o <= start_q >= START_W'(PHY_RST_CYCLES);
            mac_rst_q  <= start_q != START_W'(MAC_START_CYCLES);
        end
    end

    reset_sync u_rst_mii (
        .clk_i       (eth_rx_clk_i),
        .rst_async_i (mac_rst_q),
        .rst_o       (mii_rst)
    );

    reset_sync u_rst_mii_tx (
        .clk_i       (eth_tx_clk_i),
        .rst_async_i (mac_rst_q),
        .rst_o       (mii_tx_rst)
    );

    assign eth_mdc_o = 1'b0;

    // -------------------------------------------------------------------------------------- receive path
    logic [7:0] f_tdata;
    logic       f_tvalid, f_tready, f_tlast;
    logic       e_ok, e_crc, e_rxerr, e_runt, e_over, e_ovf;
    logic [7:0] e_ovf_frames;
    logic       sfd;

    eth_rx #(
        .FIFO_ADDR_W (FIFO_ADDR_W)
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

    // ------------------------------------------------------------------------------------- DDC, receiver
    logic [31:0] bb_tdata;
    logic        bb_tvalid, bb_tready;
    logic [7:0]  c_tdata;
    logic [32:0] c_tuser;
    logic        c_tvalid, c_tready, c_tlast;
    logic        fs_locked;
    logic [31:0] fs_dropped, fs_slips, fs_early, flag_ovf, len_err;

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

    rx_chain #(
        .RRC_TAP_FILE (RRC_TAP_FILE),
        .NCO_LUT_FILE (NCO_LUT_FILE),
        .PATTERN_FILE (PATTERN_FILE),
        .COUNT_BITS   (32)  // stats fields are u32 counters
    ) u_rx (
        .clk_i            (clk),
        .rst_i            (mac_rst_q),
        .costas_kp_i      (COSTAS_KP),
        .costas_ki_i      (COSTAS_KI),
        .costas_fmax_i    (COSTAS_FMAX),
        .timing_nominal_i (TIMING_NOMINAL),
        .timing_kp_i      (TIMING_KP),
        .timing_ki_i      (TIMING_KI),
        .timing_limit_i   (TIMING_LIMIT),
        .thr64_i          (THR64),
        .flywheel_i       (FLYWHEEL),
        .depth_i          (DEPTH),
        .s_tdata_i        (bb_tdata),
        .s_tvalid_i       (bb_tvalid),
        .s_tready_o       (bb_tready),
        .m_tdata_o        (c_tdata),
        .m_tuser_o        (c_tuser),
        .m_tlast_o        (c_tlast),
        .m_tvalid_o       (c_tvalid),
        .m_tready_i       (c_tready),
        .locked_o         (fs_locked),
        .dropped_o        (fs_dropped),
        .slips_o          (fs_slips),
        .early_o          (fs_early),
        .flag_ovf_o       (flag_ovf),
        .len_err_o        (len_err)
    );

    assign uart_txd_o = 1'b1;

    // ------------------------------------------------------------------------------------------ counters
    // Cumulative since the MAC left reset, mod 2^32. Order = docs/protocol.md "Stats" field table.
    localparam int N_STATS = 25;
    logic [31:0] cnt_q [4:18];   // fields 4..16, 18; 0..3 are the ingest's, 17 the MAC restarts, 19..24 rx_chain's
    logic        tx_underrun;

    always_ff @(posedge clk) begin
        if (mac_rst_q) begin
            for (int k = 4; k <= 18; k++) cnt_q[k] <= '0;
        end else begin
            cnt_q[4]  <= cnt_q[4]  + 32'(e_ok);
            cnt_q[5]  <= cnt_q[5]  + 32'(e_crc);
            cnt_q[6]  <= cnt_q[6]  + 32'(e_rxerr);
            cnt_q[7]  <= cnt_q[7]  + 32'(e_runt);
            cnt_q[8]  <= cnt_q[8]  + 32'(e_over);
            if (e_ovf) cnt_q[9] <= cnt_q[9] + 32'(e_ovf_frames);
            cnt_q[10] <= cnt_q[10] + 32'(u_ok);
            cnt_q[11] <= cnt_q[11] + 32'(u_filt);
            cnt_q[12] <= cnt_q[12] + 32'(u_csum);
            cnt_q[13] <= cnt_q[13] + 32'(u_mal);
            if (32'(fifo_level) > cnt_q[14]) cnt_q[14] <= 32'(fifo_level);
            cnt_q[15] <= cnt_q[15] + 32'(bb_tvalid && bb_tready);
            cnt_q[16] <= cnt_q[16] + 32'(tx_underrun);
            cnt_q[18] <= cnt_q[18] + 32'(cp_tvalid && cp_tready && cp_tlast);
        end
    end

    logic [N_STATS*32-1:0] stats;
    always_comb begin
        stats[0*32 +: 32] = ok_cnt;
        stats[1*32 +: 32] = bad_cnt;
        stats[2*32 +: 32] = gap_cnt;
        stats[3*32 +: 32] = lost_cnt;
        for (int k = 4; k <= 16; k++) stats[k*32 +: 32] = cnt_q[k];
        stats[17*32 +: 32] = mac_restarts_q;
        stats[18*32 +: 32] = cnt_q[18];
        stats[19*32 +: 32] = 32'(fs_locked);
        stats[20*32 +: 32] = fs_dropped;
        stats[21*32 +: 32] = fs_slips;
        stats[22*32 +: 32] = fs_early;
        stats[23*32 +: 32] = flag_ovf;
        stats[24*32 +: 32] = len_err;
    end

    // ------------------------------------------------------------------------------------- transmit path
    // Reply address: the sender of the last datagram udp_rx accepted (its src_* are stable through the datagram
    // and still valid on the ok_o pulse that ends it). Taken from replay datagrams only (udp_rx filters the rest).
    logic [47:0] peer_mac_q;
    logic [31:0] peer_ip_q;
    logic        peer_valid_q;

    always_ff @(posedge clk) begin
        if (mac_rst_q) begin
            peer_valid_q <= 1'b0;
        end else if (u_ok) begin
            peer_mac_q   <= src_mac;
            peer_ip_q    <= src_ip;
            peer_valid_q <= 1'b1;
        end
    end

    logic [7:0] sp_tdata, cp_tdata, a_tdata, t_tdata;
    logic       sp_tvalid, sp_tready, sp_tlast, cp_tvalid, cp_tready, cp_tlast;
    logic       a_tvalid, a_tready, a_tlast, t_tvalid, t_tready, t_tlast, t_sent, t_over;

    stats_packet #(
        .N_FIELDS (N_STATS),
        .PERIOD   (STATS_PERIOD)
    ) u_stats (
        .clk_i      (clk),
        .rst_i      (mac_rst_q),
        .enable_i   (peer_valid_q),
        .fields_i   (stats),
        .m_tdata_o  (sp_tdata),
        .m_tvalid_o (sp_tvalid),
        .m_tready_i (sp_tready),
        .m_tlast_o  (sp_tlast)
    );

    cadu_packet u_cadu_pkt (
        .clk_i      (clk),
        .rst_i      (mac_rst_q),
        .enable_i   (peer_valid_q),
        .s_tdata_i  (c_tdata),
        .s_tuser_i  (c_tuser),
        .s_tlast_i  (c_tlast),
        .s_tvalid_i (c_tvalid),
        .s_tready_o (c_tready),
        .m_tdata_o  (cp_tdata),
        .m_tvalid_o (cp_tvalid),
        .m_tready_i (cp_tready),
        .m_tlast_o  (cp_tlast)
    );

    pkt_arb2 u_arb (
        .clk_i       (clk),
        .rst_i       (mac_rst_q),
        .s0_tdata_i  (cp_tdata),
        .s0_tvalid_i (cp_tvalid),
        .s0_tready_o (cp_tready),
        .s0_tlast_i  (cp_tlast),
        .s1_tdata_i  (sp_tdata),
        .s1_tvalid_i (sp_tvalid),
        .s1_tready_o (sp_tready),
        .s1_tlast_i  (sp_tlast),
        .m_tdata_o   (a_tdata),
        .m_tvalid_o  (a_tvalid),
        .m_tready_i  (a_tready),
        .m_tlast_o   (a_tlast)
    );

    udp_tx u_udp_tx (
        .clk_i      (clk),
        .rst_i      (mac_rst_q),
        .cfg_mac_i  (OWN_MAC),
        .cfg_ip_i   (OWN_IP),
        .s_tdata_i  (a_tdata),
        .s_tvalid_i (a_tvalid),
        .s_tready_o (a_tready),
        .s_tlast_i  (a_tlast),
        .s_tuser_i  (1'b0),
        .dst_mac_i  (peer_mac_q),
        .dst_ip_i   (peer_ip_q),
        .dst_port_i (STATS_PORT),
        .src_port_i (UDP_PORT),
        .m_tdata_o  (t_tdata),
        .m_tvalid_o (t_tvalid),
        .m_tready_i (t_tready),
        .m_tlast_o  (t_tlast),
        .sent_o     (t_sent),
        .oversize_o (t_over)
    );

    eth_tx u_eth_tx (
        .clk_i       (clk),
        .rst_i       (mac_rst_q),
        .s_tdata_i   (t_tdata),
        .s_tvalid_i  (t_tvalid),
        .s_tready_o  (t_tready),
        .s_tlast_i   (t_tlast),
        .underrun_o  (tx_underrun),
        .mii_clk_i   (eth_tx_clk_i),
        .mii_rst_i   (mii_tx_rst),
        .mii_txd_o   (eth_txd_o),
        .mii_tx_en_o (eth_tx_en_o)
    );

    // ------------------------------------------------------------------------------------------ status
    // Runts and oversize frames are not counted: other hosts' traffic on the cable can produce them.
    // Datagrams for other groups/ports (u_filt) are not errors either.
    logic err_q;
    logic [26:0] beat_q;

    always_ff @(posedge clk) begin
        if (mac_rst_q) err_q <= 1'b0;
        else if (e_crc || e_rxerr || e_ovf || u_csum || u_mal || tx_underrun || bad_cnt != '0 || gap_cnt != '0 ||
                 flag_ovf != '0 || len_err != '0)
            err_q <= 1'b1;
    end

    always_ff @(posedge clk) begin
        if (rst) beat_q <= '0;
        else     beat_q <= beat_q + 1'b1;
    end

    logic cadu_led_q;

    always_ff @(posedge clk) begin
        if (mac_rst_q)                               cadu_led_q <= 1'b0;
        else if (cp_tvalid && cp_tready && cp_tlast) cadu_led_q <= ~cadu_led_q;
    end

    assign led_o = {err_q, cadu_led_q, fs_locked, beat_q[26]};

    // Unused: BTN0, the RX timestamp, the replay's source/destination ports, the TX frame-sent and oversize pulses
    // (the largest payload, a CADU packet, is 1,048 bytes, below 1,472).
    logic unused;
    assign unused = ^{btn0_i, sfd, src_port, dst_port, t_sent, t_over};

endmodule

`default_nettype wire
