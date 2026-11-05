`default_nettype none

// Phase B board bring-up on the Arty A7-100T, without Ethernet (fpga-coord gates eth-core-v0.1/v0.2 not met):
//
//   iq_rom_source (cu8 snippet in BRAM) -> ddc_top -> capture_dump (BRAM) -> uart_tx -> USB-UART -> host
//
// After reset (or the RESET button) the snippet plays once through the DDC at full speed with real backpressure;
// the N_SAMPLES/4 outputs are captured and sent over the UART. BTN0 sends the capture again.
// scripts/ddc_board_check.py compares every output with the bit-true model.
// LEDs: LD4 heartbeat, LD5 snippet played, LD6 capture full, LD7 dumping.
module arty_ddc_rom_top #(
    parameter int          N_SAMPLES     = 65536,        // snippet length; outputs = N_SAMPLES / 4 (CIC /4)
    parameter logic [31:0] FREQ_WORD     = 32'h2580_0000, // 150 kHz at 1.024 MS/s = 600 * 2^20 (ADR 0003)
    parameter int          CLKS_PER_BIT  = 868,          // 115,200 baud at 100 MHz
    parameter string       ROM_FILE      = "iq_rom.mem",
    parameter string       NCO_LUT_FILE  = "nco_lut.mem",
    parameter string       COMP_TAP_FILE = "comp_fir_taps.mem"
) (
    input  wire logic       clk100_i,     // E3, 100 MHz oscillator
    input  wire logic       ck_rst_n_i,   // C2, RESET button, active-low
    input  wire logic       btn0_i,       // D9, BTN0
    output      logic       uart_txd_o,   // D10, FPGA -> host
    output      logic [3:0] led_o
);

    logic        rst, btn0, btn0_q, dump;
    logic [15:0] iq_tdata;
    logic        iq_tvalid, iq_tready, rom_done;
    logic [31:0] bb_tdata;
    logic        bb_tvalid, bb_tready;
    logic [7:0]  tx_tdata;
    logic        tx_tvalid, tx_tready;
    logic        full, busy;
    logic [26:0] beat_q;

    reset_sync u_rst (
        .clk_i       (clk100_i),
        .rst_async_i (!ck_rst_n_i),
        .rst_o       (rst)
    );

    cdc_sync_bit u_btn0 (
        .clk_i (clk100_i),
        .d_i   (btn0_i),
        .q_o   (btn0)
    );

    // Rising edge of BTN0. Bounces land while the ~6 s dump is busy, and capture_dump ignores dump_i then.
    always_ff @(posedge clk100_i) btn0_q <= btn0;
    assign dump = btn0 && !btn0_q;

    iq_rom_source #(
        .N_SAMPLES (N_SAMPLES),
        .ROM_FILE  (ROM_FILE)
    ) u_rom (
        .clk_i      (clk100_i),
        .rst_i      (rst),
        .m_tdata_o  (iq_tdata),
        .m_tvalid_o (iq_tvalid),
        .m_tready_i (iq_tready),
        .done_o     (rom_done)
    );

    ddc_top #(
        .NCO_LUT_FILE  (NCO_LUT_FILE),
        .COMP_TAP_FILE (COMP_TAP_FILE)
    ) u_ddc (
        .clk_i       (clk100_i),
        .rst_i       (rst),
        .freq_word_i (FREQ_WORD),
        .s_tdata_i   (iq_tdata),
        .s_tvalid_i  (iq_tvalid),
        .s_tready_o  (iq_tready),
        .m_tdata_o   (bb_tdata),
        .m_tvalid_o  (bb_tvalid),
        .m_tready_i  (bb_tready)
    );

    capture_dump #(
        .N_WORDS (N_SAMPLES / 4)
    ) u_cap (
        .clk_i      (clk100_i),
        .rst_i      (rst),
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
        .clk_i      (clk100_i),
        .rst_i      (rst),
        .s_tdata_i  (tx_tdata),
        .s_tvalid_i (tx_tvalid),
        .s_tready_o (tx_tready),
        .txd_o      (uart_txd_o)
    );

    always_ff @(posedge clk100_i) begin
        if (rst) beat_q <= '0;
        else     beat_q <= beat_q + 1'b1;
    end

    assign led_o = {busy, full, rom_done, beat_q[26]};

endmodule

`default_nettype wire
