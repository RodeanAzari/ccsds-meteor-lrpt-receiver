The DDC on the Arty A7-100T fed over Ethernet: gs-replay streams the same 65,536-sample snippet as the BRAM test
(`ddc_board.csv`) as 128 IQ replay datagrams (docs/protocol.md) through fpga-eth-core's eth_rx and udp_rx and
iq_udp_ingest into ddc_top, and the first 16,384 outputs are dumped over the UART. Zero mismatches means every
sample of every datagram reached the DDC once, in order, unaltered, at the replay speed recorded in the row: a
lost, damaged, duplicated or reordered datagram would shift or corrupt every later output. It does not measure
sustained throughput or loss over a long replay; the ingest gap counters go to the host with the Phase E stats
packet.
