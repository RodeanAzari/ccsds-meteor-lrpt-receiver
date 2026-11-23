# board_gs_rx_real

- **Commit:** `8c70f2d0bf3b85cbbcc006f9184512cc5a593544`
- **Command:** `PYTHONPATH=. python scripts/board_gs_rx.py build/real_pass/2026-11-21T194551Z_cut.cu8 /home/rodea/recordings/2026-11-21_satdump/meteor_m2-x_lrpt.cadu --iface 192.168.10.1 --speed 5,1 --tune 150000 --bit build/board/arty_rx_eth_top.bit --idle 60 --recording 2026-11-21T1943Z_meteor-m2-4_part2.cu8`
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1
- **Input:** real recording `2026-11-21T1943Z_meteor-m2-4_part2.cu8` (data/MANIFEST.md).

The whole receiver on the Arty decodes the real Meteor-M N2-4 pass: 5,587 RS-good CADUs from one reset and one NCO word, identical in their 892 data bytes to SatDump on all 4,566 frames both have, and the ground station's space packets equal SatDump's wherever both decoders have the frames. This is Phase E's real decode.

**Run.** A 740 s cut of the 2026-11-21 recording (19:45:51–19:58:11 UTC, `dd bs=2048 skip=480000 count=740000`; it holds every SatDump frame) streamed by gs-replay to `arty_rx_eth_top`, received by gs-rx and compared by gs-diff with SatDump 1.2.2's decode of the whole recording. The cut starts at 19:45:51 because the coarse estimator rejects the first 2 s at 19:45:35 (signal too weak); from there it gives −357.1 Hz (word 0x25692600), on the bit-true study's carrier track (−376 Hz median for the 19:46:03 chunk).

**One carrier setting for the whole pass.** The NCO word is set once, before the first sample; the Costas loop then follows the Doppler from about −360 Hz to −6.4 kHz (real_pass_fixed.csv, `median_carrier_hz`) on its own, without losing the frames in between: no gap opens in the middle of the pass.

**Results (both rows).** 5,912 CADUs sent, 5,587 RS-good, 325 RS-failed (gs-rx's RS gate keeps them out of cadus.bin), 4,173 RS symbols corrected; nothing lost anywhere (board ingest 0, gs-rx `cadu_seq_missing` 0, ring never full, host TX drops 0). 76 frame-sync slips over the pass. Both rows ran at the requested rate (5.00× and 1.00×) and their cadus.bin files are byte-identical, and identical to an earlier run of the same cut whose 5× request reached only 3.20×: the decode does not depend on the replay rate.

**Against SatDump.** 4,566 common frames, 0 data bits differ. 2 frames differ in the ASM and 53 parity bytes differ: SatDump writes the received ASM and leaves channel errors in the parity (signal-spec.md, "What gs-diff can compare"), so these are not decoder disagreements. 1,021 frames only the board has (the bit-true chain had 1,003 such; same causes: frames before SatDump acquires and in SatDump's gaps in the fade). 17 SatDump frames the board lacks, all among SatDump's last 92 (index 4,491 onward), in the fade at loss of signal.

**Space packets (gs-rx → scripts/packet_diff.py vs. SatDump's demux).** 22,295 packets from the board, 18,208 from SatDump; 18,176 equal. Every other packet is explained: 4,114 only ours and 23 only SatDump's sit in frames the other side lacks, and 9 SatDump packets are damaged (they cross a counter gap in its stream; the 5 that differ and 4 of SatDump's only are among them). 0 unexplained.

**Against the bit-true model (real_pass_fixed.csv).** The study found 5,585 RS-good frames and missed 1 SatDump frame; the board, 5,587 and 17. The study restarts cold every 30 s with a fresh coarse estimate; the board runs the whole pass from one reset. A diagnostic board run (not in this CSV; docs/log.md 2026-11-22) restarted the board cold at 19:56:19 with a fresh estimate (−6,358 Hz) and replayed only the last 112 s: it found 14 of the 17, and 89 of SatDump's last 92 frames against 75 here. So state the continuous run carries into the fade costs those frames, not the decoder's arithmetic; which state (Costas integrator holding the whole −6.4 kHz, AGC, frame-sync history) was not isolated.

**Limits.** One recording, one pass. The bitstream is from 2026-11-09; the RTL changed since only in coverage and formal blocks excluded from synthesis.
