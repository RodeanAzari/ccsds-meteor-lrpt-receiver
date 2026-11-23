The Viterbi decoder RTL (`fec_viterbi`) clock by clock in simulation, around its first traceback walk (clock 0), with no input gaps or output stalls. These are the rows the Phase D waveform figure is drawn from.

- **Fill:** before clock 0 the ACS array takes one trellis step per clock (`s_tvalid` and `s_tready` both high), and each step's 64 decisions go into the traceback memory as one row (`wr_ptr` counts up).
- **Walk:** at clock 0 the traceback has 96 rows and starts walking back from the newest one (`tb_busy`). `rd_ptr` counts down one row per clock and `state` follows the decisions from state 0 (ADR 0008).
- **Waiting while it walks:** the array has already taken one more step and holds its row in its output register (`dec_tvalid`). It keeps `s_tready` low until the walk ends. The walk ends in one decoded bit (`m_tvalid`, clock 97). On the next clock the traceback takes the waiting row and the array takes its next step, and the next walk starts the clock after that (clock 99).
- **In steady state:** one walk takes 99 clocks (depth 96 + 3) and covers exactly one step, one row and one bit. The test asserts this for every walk.

The 99 clocks per bit match `viterbi_rtl_sim.csv`: 95.9 clocks per bit averaged over a run that includes the fill. That leaves 14x headroom against the 1,389 clocks per bit available at 100 MHz and 72 kbit/s.
