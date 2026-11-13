# Functional coverage

`make cov` closes the coverage bins of buildplan §8.2. Every cocotb suite (`make sim`, `sim-slow`, `sim-full`) is built
with Verilator `--coverage-user`. That counts the `cov_*` cover properties written next to the RTL they observe. Then
`scripts/coverage_report.py` merges the runs into `data/results/coverage.csv`. Closure means every bin is hit or
listed below with a reason. A listed bin that gets hit fails the report as a stale exclusion.

| Bin group (buildplan §8.2) | Bins | Where |
|---|---|---|
| Sync FSM states and transitions | confirm (two frames, first early), a due peak failing, queue full, queue at 1–4, lock held on time, slips at −2..+2 (0: hypothesis change), flywheel frame, lock lost | `fec_fs_fsm.sv` |
| Each phase hypothesis winning | a confirm on each of the 4 hypotheses | `fec_fs_fsm.sv` |
| RS errors 0–16 plus uncorrectable | a codeword with each of 0..16 corrections, and one failing | `fec_cadu.sv` |
| Viterbi normalization events | a metric wrapping past 2^9: modulo metrics have no normalization (ADR 0006), and the wrap is its counterpart | `fec_acs_array.sv` |
| Backpressure per interface | input and output stalled (`tvalid && !tready`) on every streaming block | each block |
| Loop lock states | none, see below | |

A bin is named by its file and cover name (`fec_cadu.sv:cov_rs_corrected_7`), so hits from block tests and chain
tests add up. Indexed bins are written one cover per line, never in a generate loop: Verilator merges a loop's
covers into a single point (`g_cov_rs[*]`), which would hide a missed index. `ddc_comp_fir.sv`'s bins count both its
instances, the DDC compensation FIR and the RRC (`sync_rrc.sv`).

## Exclusions

| Bin | Justification |
|---|---|
| `group:loop lock states` | The sync loops (AGC, Costas, timing) have no lock detector in the RTL: lock is judged by the frame sync (ADR 0002), whose states are binned above. Loop lock is measured instead: `sync_lock_range.csv`, `sync_lock_costas.csv`. |
