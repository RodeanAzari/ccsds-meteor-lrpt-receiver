Project ID: P3
@~/fpga-coord/PROTOCOL.md

Current state of the work:
progress.md

# CLAUDE.md — CCSDS Satellite Telemetry Receiver

## What this is

A Meteor-M N2-4 LRPT (72k mode, OQPSK) downlink receiver in SystemVerilog on a Digilent Arty A7-100T, with C++
ground-station tools on the host. RTL-SDR `.iq` recordings are replayed over UDP to the board: DDC → RRC → timing +
carrier recovery → encoded-ASM sync → Viterbi K=7 r½ → NRZ-M → derandomizer → RS(255,223)×4 → CADUs back to the host.

**Portfolio project:** working RTL is half the deliverable; the other half is evidence (decoded image, constellation
plots, BER curves, video, a full README). **A phase without its numbers and media is not done.**

**Languages:** SystemVerilog (RTL), Python/NumPy (golden model, cocotb, analysis), C++20 (ground station).

## Build plan (not imported)

The detailed spec lives in **`docs/buildplan.md`**, with the same section numbers as before: §2 signal spec and
capture workflow, §3 receiver architecture (per block: DDC, sync, frame sync, Viterbi, RS and its reuse contract,
debug), §4 ground-station tools, §8 verification (models, cocotb scenarios and coverage bins, formal, BER campaigns,
real-pass validation), §9 phases and definitions of done, §10 out of scope, §11 portfolio captures, media rules and
the README standard. References like `CLAUDE.md §3.6` in code and docs resolve there. **Read the relevant section
before starting a phase or a block, before closing a phase (§9 checklist), and before writing the README (§11.4).**
Rules every session needs from it:
- **Stay in scope (§10):** no transmit path, LDPC/turbo, SLE, live RF into the FPGA, 80k mode, other satellites.
  Descope order: RS first, then the derandomizer; DDC → sync → Viterbi always survives. Say so before drifting.
- **Signal parameters:** `docs/signal-spec.md` is the spec, written from SatDump's source. Never guess one; if code
  and spec disagree, stop and flag it. SatDump before the golden model, golden model before RTL: no RTL block until
  its Python model exists and produces test vectors.
- **Interfaces (§3.1):** AXI4-Stream between every block (`tlast` = CADU boundary, `tuser` = sideband); every block
  honours backpressure; nothing dropped silently, every overflow point has a counter. Packet formats live only in
  `docs/protocol.md`.
- **Fixed point (§3.2):** every signal's format, rounding and saturation is in `docs/fixed-point.md`; the bit-true
  model uses exactly the RTL's widths and rounding; truncation is never silent.

## Dependencies and cross-project rules

- `fpga-eth-core` (P2) at `rtl/eth/` as a git submodule pinned to a tag; `tb-common` (P2) pip-installed from git at a
  tag. **Never edit, copy or build from another project's working tree**; read it for reference only. Changes go
  through the owner's `docs/requests.md` / fpga-coord requests.
- Gates: until `eth-core-v0.1`, hardware tests use IQ snippets in a BRAM ROM (no temporary Ethernet path). Until
  `eth-core-v0.2`, results come back over UART or ILA. When blocked, say which tag is missing and work on a phase
  that doesn't need it.
- The README's "Shared components" table links every shared repo used; add a row when a new one is consumed.

## Current status

<!-- Update as phases complete. Never mark a phase done until its buildplan §9 checklist passes in full,
     INCLUDING the portfolio items. -->

| Phase | Status | Key result |
|---|---|---|
| 0 — Signal spec + capture kit | IN PROGRESS | `docs/signal-spec.md` written from source, not yet confirmed on a recording |
| A — Python golden model | IN PROGRESS | Float model decodes synthetic signals end to end; not yet run on a real recording |
| B — Digital downconverter | IN PROGRESS | DDC bit-exact on the Arty (UART and ILA, 16,384 outputs); Ethernet replay waits on eth-core-v0.1 |
| C — Synchronization | IN PROGRESS | Sync chain RTL bit-exact in simulation, output decodes; lock ±15 kHz in 16–35 ms (`sync_lock_range.csv`). Real recording pending |
| D — Viterbi + frame sync | NOT STARTED | — |
| E — Reed-Solomon + integration + real decode | NOT STARTED | — |
| F — C++ ground station | NOT STARTED | — |

## Rules for Claude

- **"Done" means verified:** tests pass, `make lint` clean, `make ci` passes locally. A phase is done when its full
  buildplan §9 checklist passes and the user has confirmed the physical captures.
- **Record decisions:** every architectural choice gets an ADR in `docs/decisions/` (§5.5), with rejected options.
- **Portfolio moments:** at the end of every phase and when something visually striking works (first lock, first
  frame, first real decode), generate the plots, list the exact physical captures for the user, add them to
  `docs/portfolio-todo.md`, and wait for the user before marking the phase done (buildplan §11.1).
- **Lab notebook:** append a `docs/log.md` entry at the end of every working session: dated, numbers measured, bugs
  as symptom → root cause → fix (buildplan §11.3).
- **Progress file:** read `progress.md` at session start; update it when progress, next steps or a key decision
  changes. Replace stale entries; detail goes to `docs/log.md`, `docs/decisions/` or `data/results/`.
- **Front page:** update this status table and the README results at the end of every phase (README standard:
  buildplan §11.4).
- **Keep always-loaded docs lean.** CLAUDE.md ≤ 250 lines and `progress.md` ≤ 150 lines. Trim them at the end of
  every session that edits them, and at once if either is over. Keep only what a future session would get wrong
  without being told (current state, open work, rules, traps that cost real time). Cut finished-work narratives,
  dated history, reasons the code, tests, commits or reports already record, and duplicates of other docs. Move
  what must be kept but isn't needed every turn (the spec, append-only measurement tables, long verification
  detail) to files that aren't imported, such as `docs/buildplan.md` and `docs/measurements.md`, and leave a
  one-line pointer. Never edit the shared `~/fpga-coord/PROTOCOL.md`; propose trims to the user instead.
- **Small, frequent commits** (§5.4).

## Measurement rules

- **Never invent a number.** Unmeasured values are `[TBD]`. Every reported number links to its CSV in
  `data/results/` or a recording in `data/MANIFEST.md`. No estimates dressed as results.
- Every result CSV has a sidecar `.md` (commit, exact command, tool versions, input recording or seed, interpretation),
  written by `analysis/common.write_result()` with the interpretation from `analysis/interpretations/<name>.md`.
- Plots come only from `make plots` over `data/results/`: reproducible, never hand-edited, axes labeled with units.
  Media in `docs/media/YYYY-MM-DD_phase-x_description.ext`; GIFs ≤ 8 MB; videos never committed.
- BER points need ≥ 100 bit errors, otherwise report an upper bound. Label pre-/post-FEC explicitly.
- Real recordings: SatDump decodes them first; never debug against a live pass. Full recordings never go in the
  repo; list each in `data/MANIFEST.md` (SHA-256, satellite, UTC, elevation, frequency, rate, gain, mode, SatDump
  version). One short real IQ snippet (< 5 MB) may be committed in `data/samples/`.
- Tests encode why behaviour matters. Prove each check can fail: plant the bug it guards against and confirm it is
  caught, and note any check a mutant slipped past.

## 1. Hardware

- **FPGA:** Arty A7-100T, `xc7a100tcsg324-1`: 63,400 LUTs, 240 DSP48E1, 135 BRAM36, 256 MB DDR3L; DP83848J 10/100 PHY
  over MII. One board, shared between projects: `coord.py board claim P3 "<reason>"` before any hardware run.
- **No RF front end.** RF is captured on the host: V-dipole → SAWbird+ NOAA (bias tee on) → RTL-SDR Blog V3 → USB.
  Start tuner gain low and raise it while watching the waterfall; record the gain. Kit detail: buildplan §1.
- **Capture:** 1.024 MS/s, unsigned 8-bit interleaved I/Q, tuned 100–250 kHz off the signal (137.9 MHz; check the
  frequency and **72k vs. 80k mode** before every pass). Valid RTL-SDR rates only: 225–300 kS/s or 0.9–3.2 MS/s.
- **Host:** Linux (WSL2 at `~/CCSDS`; board USB through usbipd-win), cabled directly to the Arty.

## 5. Coding standards

### 5.1 SystemVerilog
- `logic` only; `always_ff` / `always_comb`, never bare `always`; `<=` sequential, `=` combinational. Default every
  `always_comb` output (no latches).
- One module per file, filename = module name; named port connections only. Every file starts with
  `` `default_nettype none `` and ends restoring `` `default_nettype wire ``.
- Suffixes `_i`, `_o`, `_n` (active-low), `_q` (registered), `_d` (next state). Parameters `UPPER_CASE`.
- Reset synchronous, active-high, a synchronizer per clock domain; reset control state only.
- Parameterize widths, ratios, gains, depths and RS (m, n, k, poly, generator); no magic numbers; every `localparam`
  comments its source (e.g. `// signal-spec.md §RS`).
- CDC only through `rtl/lib/cdc_*` or fpga-eth-core's FIFO; every crossing listed in `docs/design.md` and
  constrained in XDC. Vendor primitives only in `rtl/lib/xilinx/` wrappers (everything simulates in Verilator).
- SVA next to the RTL it checks, visible to Verilator and SymbiYosys. No `$display`, delays or `initial` in `rtl/`
  except BRAM/ROM init.
- Zero Verilator `-Wall` warnings; any waiver inline, justified, minimal.

### 5.2 Python
Python 3.11+ with type hints, `mypy --strict` on `model/`, `ruff` (line length 120), `pytest`. Deterministic and
seeded; no plotting in model code.

### 5.3 C++ (ground station)
C++20, `-Wall -Wextra -Werror`, clang-format, clang-tidy and cppcheck clean, ASan/UBSan in Debug. Data path: no
exceptions or allocation after start-up, fixed-width types, explicit endianness, `std::bit_cast`/`memcpy` not
punning. GoogleTest on every parser with captured frames; the packet parser is fuzzed (libFuzzer).

### 5.4 Commits and tags
Small, phase-tagged commits (`sync: …`, `docs: …`). Milestone tags `v0.1-ddc`, `v0.2-sync-lock`, `v0.3-viterbi`,
`v0.4-rs`, `v0.5-first-real-decode`, `v1.0`; never with negative slack. Never commit Vivado projects, build output
or full IQ recordings.

### 5.5 Decision records
`docs/decisions/NNNN-title.md`: Context, Options considered, Decision, Consequences, Measured evidence.
`docs/design.md` summarizes and links them. Required: NCO implementation, CIC order/decimation split, interpolator
type, OQPSK timing approach, soft-decision width, path-metric normalization, survivor memory, traceback depth, BM
variant, RS instance count, phase-ambiguity strategy, IQ transport format.

## 6. Toolchain and build

Vivado ML Standard 2025.2 (batch Tcl via `scripts/vivado.sh`), Verilator 5.050, cocotb 2.1.0 (+ tb-common),
SymbiYosys, Python 3 (NumPy, SciPy, matplotlib, pytest), C++20/CMake/GoogleTest/clang-tidy/cppcheck/libFuzzer,
SatDump 1.2.2 (stable release, not the V2 alpha; golden decoder), `rtl_sdr`. Versions pinned in `docs/toolchain.md`.

```
make setup  lint  lint-py  sim (< 5 min)  sim-full (long runs)  model-test  gs  gs-test  gs-lint  ci
make synth-ooc TOP=<top>   make board [ILA=1]  prog  board-check  ila-capture
make ddc-rtl-results  sync-rtl-results  gs-replay-results  synthetic-iq  ber (model)  *-study  plots  clean
not yet implemented (fail loudly): cov  formal  fuzz  synth  impl  reports
```

- `make ci` = lint-py, lint, model-test, sim, gs-test, gs-lint; GitHub Actions runs it on every push.
  **A broken CI gets fixed before anything else.**
- Vivado runs in batch mode via `syn/` Tcl, no GUI-only steps. Targets must work from a clean checkout. Planned
  targets and CI contents: buildplan §6.
- Vivado and the board are local only; commit timing and utilization reports with the RTL that produced them.
  Timing closure is required: no milestone with negative slack.

## 7. Repository layout

```
rtl/{eth (submodule, never edit), lib, ddc, sync, fec, io, top}  (synthesizable only)   tb/{cocotb, formal}
model/ (float, bit-true, channel)   gs/ (C++)   analysis/ (studies, plots, interpretations/)   syn/ constr/ scripts/
data/{samples, truth, results, MANIFEST.md}
docs/{buildplan, signal-spec, design, fixed-point, viterbi, protocol, toolchain, log, portfolio-todo}.md,
     decisions/, reports/, media/
```

## 12. Known failure modes

- **Skipping the SatDump check on a capture:** weeks lost debugging RTL when the antenna was the problem
- **Guessing Phase 0 parameters** (RRC roll-off, differential coding, conv output order, RS basis): "almost locks" forever
- **Invalid RTL-SDR sample rate** (300–900 kS/s): the driver silently picks another rate
- **DC spike on the signal** from tuning exactly on frequency. Tune offset.
- **Treating 72k M2-x as plain QPSK**, or forgetting the half-symbol offset: the constellation smears and never settles
- **Running a plain QPSK Gardner on unaligned OQPSK:** the timing loop wanders
- **Costas bandwidth too narrow** for the Doppler sweep: lock lost mid-pass
- **Correlating the plain ASM before Viterbi:** it's convolutionally encoded, so it never matches
- **Including the first 12 encoded-ASM symbols** in the correlation: false misses
- **Viterbi path-metric overflow** after long runs: works for 1,000 frames, fails at 100,000
- **Derandomizing the ASM**, or not resetting the PN generator each frame
- **Wrong RS interleave order:** every codeword uncorrectable even with a perfect signal
- **Wrong RS basis** (conventional vs. dual): same symptom
- **CIC bit growth undersized:** overflow wraps silently
- **DSP inference failure:** multipliers in LUTs, timing fails
- **Editing `rtl/eth/` in place:** the submodule diverges from `fpga-eth-core`
- **Opening the board's serial port resets the loaded design:** dumps carry a CRC-32 and the host skips cut-off ones
- **Vivado deletes `.mem` files in its run directory at exit:** generate ROM images outside it
- **Synthesis renames nets:** ILA insertion by net name must fail loudly on a rename
- **A fast sink never stalls a slow chain:** a chain test only exercises inner backpressure when the output is
  slower than the chain (`test_sync_top.py`); size the harness drain window to the sink rate
