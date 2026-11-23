# viterbi_board_ila_pm

- **Commit:** `8346bb2baa4ffe589561684989a769c937deab0c`
- **Command:** `PYTHONPATH=. python scripts/ila_viterbi.py check build/board/ila_acs.csv build/board/arty_rx_eth_top_ila.ltx data/samples/2026-11-21T195100Z_meteor-m2-4_2.4s.cu8`
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1
- **Input:** real recording `data/samples/2026-11-21T195100Z_meteor-m2-4_2.4s.cu8` (data/MANIFEST.md).

The first 200 steps of the ILA capture in viterbi_board_ila.csv, for the plot: each state's path metric minus the best state's (unwrapped by the RTL's modulo compare against state 0), with the step's two soft symbols. Step 0 is the decoder's first step after reset, where all metrics are equal; within about 20 steps they spread to the 0–30 range they then keep. A metric of 0 marks a survivor of the best path.
