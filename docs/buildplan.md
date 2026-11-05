# Build plan — CCSDS Meteor-M LRPT receiver

The detailed build spec, moved out of CLAUDE.md so it isn't loaded on every turn. **Section numbers match the old
CLAUDE.md**, so references like `CLAUDE.md §3.6` in code, docs and ADRs resolve here (§5, §7, §12 and the current §6 live in
CLAUDE.md). Not imported anywhere: read the section you need when you start a phase or a block.

Sections: §1 hardware and capture kit · §2 signal specification and capture · §3 receiver architecture ·
§4 C++ ground station · §6 planned build targets and CI · §8 verification · §9 phases and definitions of done · §10 out of scope ·
§11 portfolio deliverables and README standard.

---

## 1. Hardware

**FPGA:** Digilent Arty A7-100T, `xc7a100tcsg324-1` (supported by free Vivado).
- 63,400 LUTs, 240 DSP48E1, 135 BRAM36 (4,860 Kb), 256 MB DDR3L.
- TI DP83848J 10/100 PHY over MII.
- **No RF front end.** RF is captured on the host.

**RF capture kit (ordered 2026-11-04, arriving about 2026-11-25):**

| Item | Notes |
|---|---|
| RTL-SDR Blog V3 kit with dipole | V4 was out of stock. 1 PPM TCXO, software bias tee. Configure the dipole as a **V-dipole**: two ~53 cm legs at ~120°, horizontal, oriented north–south, clear sky |
| Nooelec SAWbird+ NOAA | 137.5 MHz SAW filter + two-stage LNA (≥30 dB gain). Keeps FM broadcast from overloading the dongle. Powered from the V3's bias tee |

**Signal chain:** V-dipole → dipole's RG174 cable → SAWbird+ input → SAWbird+ output → included SMA M-M adapter → V3 → USB → host. No other coax.

- **Bias tee on** for every capture: in SatDump, or `rtl_sdr -T`. Use only one SAWbird power source at a time.
- **Gain:** the SAWbird's ≥30 dB can overload the dongle. Start the tuner gain low and raise it while watching SatDump's waterfall for spurs or a raised noise floor, before recording. Record the gain for every capture in `data/MANIFEST.md`.

Receive-only operation needs no licence in Canada. A QFH antenna (circular polarization, matches the satellite's RHCP) is a later upgrade, not a prerequisite.

**Host:** Linux machine cabled directly to the Arty.

---

## 2. Signal specification

### 2.1 Target: Meteor-M N2-4 LRPT, 72k mode (SatDump pipeline `meteor_m2-x_lrpt`)

| Parameter | Value | Confidence |
|---|---|---|
| Frequency | **137.9 MHz**. It has switched to 137.1 MHz in the past. | Check before every pass |
| Modulation | **OQPSK** (Q offset by half a symbol). The older Meteor-M N2 used plain QPSK; N2-2/3/4 use OQPSK. | High |
| Symbol rate | 72,000 sym/s, giving 144 kbit/s coded and 72 kbit/s after Viterbi | High |
| Convolutional code | K = 7, r = ½, G1 = 171₈ (1111001), G2 = 133₈ (1011011) | High. Output order and inversion → Phase 0 |
| Frame | CADU = 1,024 bytes: ASM `0x1ACFFC1D` (4 B) + 1,020 B randomized CVCDU | High |
| Randomizer | CCSDS PN: h(x) = x⁸+x⁷+x⁵+x³+1, all-ones seed, 255-byte period. **Reset at the start of each frame, after the ASM. The ASM is not randomized.** | High |
| Reed-Solomon | RS(255,223) over GF(2⁸), field poly x⁸+x⁷+x²+x+1 (0x187), generator roots α^(11j) for j = 112…143, E = 16. **Interleave depth 4: byte *i* belongs to codeword *i* mod 4.** | High. Symbol basis (conventional vs. dual) → Phase 0 |
| Matched filter | RRC; roll-off → Phase 0 | Verify |
| Differential coding, I/Q swap/conjugation | → Phase 0 | Verify |
| Doppler at 137.9 MHz | Up to ±3.4 kHz, sweeping through the pass, plus the RTL-SDR TCXO offset | Physics |

**SatDump is the reference implementation.** Every "Phase 0" item gets read from SatDump's M2-x 72k pipeline definition and the module source, then written into `docs/signal-spec.md`, citing the source file and commit. A wrong guess costs weeks of "almost locks".

### 2.2 Mode check before every capture

Meteor satellites have switched between 72k and **80k** mode with little notice. 80k mode adds a convolutional interleaver, with state large enough to need DDR3, plus inserted sync words. **This receiver targets 72k only.**

Check a current status source before every capture. If the satellite is in 80k mode, wait, or use an archived 72k recording. Field test: at a 72k setting, an 80k signal never resolves to four clean points.

### 2.3 Capture settings

- **Valid RTL-SDR rates only:** 225–300 kS/s or 900 kS/s–3.2 MS/s. Anything in between makes the driver silently pick another rate. **Capture at 1.024 MS/s**: ~14.2 samples/symbol and 16.4 Mb/s at 8-bit I/Q, well inside the 100 Mb/s link.
- **Tune 100–250 kHz off the signal** and let the NCO mix it down. That keeps the RTL-SDR's DC spike out of the band.
- **Raw format:** unsigned 8-bit interleaved I/Q (midpoint 127.5). Record raw. No resampling, no conversion by tools.
- **File size:** a 15-minute pass is ~1.8 GB.

### 2.4 Capture workflow: record, then replay

**Never debug against a live pass.**

| Stage | Action |
|---|---|
| 0 | Download a public Meteor M2-x 72k IQ recording. Decode it with SatDump. Start the golden model against it. **Do this before buying the kit.** |
| 1 | SatDump pass prediction → record raw IQ (`rtl_sdr` or a SatDump baseband recording at the settings above) |
| 2 | **Decode your recording with SatDump first.** If SatDump can't decode it, the antenna or capture is the problem, not the RTL. SatDump's CADUs become ground truth. |
| 3 | Feed the IQ into Verilator/cocotb. Compare against the golden model and against SatDump. Most development happens here. |
| 4 | Replay the file to the Arty with `gs-replay`; receive with `gs-rx`; compare with `gs-diff` |

### 2.5 Data management

- **Full recordings never go in the repo.** Store them off-repo and list each one in `data/MANIFEST.md`:
  - filename and SHA-256
  - satellite, UTC start time, maximum elevation
  - centre frequency, sample rate, gain
  - mode (72k/80k)
  - whether SatDump decoded it, and the SatDump version
- **Committed fixtures:** CCSDS test vectors and **one** short real IQ snippet (< 5 MB) around a known-good lock, in `data/samples/`.
- SatDump's ground-truth CADUs for each recording go in `data/truth/`. Use Git LFS if they're large.

---

## 3. Receiver architecture

```
 UDP IQ (8-bit unsigned I/Q, 1.024 MS/s)  ── via fpga-eth-core
   ▼
 INGEST: replay sequence check (gap counter) → subtract 127.5 → signed → DC block
   ▼
 DDC: NCO + mixer (tuning offset + Doppler pre-correction) → CIC ÷4 → compensation FIR
   ▼  256 kS/s (~3.56 samples/symbol)
 RRC matched filter                                   ◀── BER-campaign injection mux (§8.4)
   ▼
 TIMING: Farrow cubic interpolator + OQPSK-aware Gardner TED + PI loop → 2 samples/symbol
   ▼
 CARRIER: OQPSK alignment (delay I by T/2) + Costas (2nd-order PI, tracks Doppler) + AGC
   ▼  soft symbols, 3–4 bits
 ENCODED-ASM CORRELATOR: frame alignment + phase-ambiguity resolution → rotate/swap
   ▼
 VITERBI K=7 r½ (64-state, fully parallel ACS)
   ▼  bits
 ASM CHECK (every 1,024 B) → DERANDOMIZER → deinterleave ×4 → [dual-basis conv] → RS(255,223) ×4
   ▼
 CADU + stats packets (+ debug constellation samples) → UDP TX → host
```

### 3.1 Interfaces and conventions

- **AXI4-Stream between every block** (`tdata`, `tvalid`, `tready`, `tlast`, `tuser`). `tlast` marks CADU boundaries. `tuser` carries sideband such as the rotation hypothesis and flags.
- **Every block honours backpressure.** Data is never dropped silently. Every overflow point has a counter.
- **One memory-mapped block holds control and status:** NCO frequency, loop gains, thresholds and counters. The host reaches it via UDP command packets; UART is the fallback.
- **The packet formats live in `docs/protocol.md`**, the single source of truth for RTL and C++:
  - IQ replay (sequence number + samples)
  - CADU+stats: frame counter, rotation hypothesis, Viterbi metric margin, RS corrections per codeword, uncorrectable flags, sync state, cycle timestamp
  - debug constellation samples
  - control commands
- **No ARP needed.** `gs-replay` sends to a configured multicast group, the same RX filter style as the order-book project. `fpga-eth-core` learns the host's MAC/IP from the source fields of received packets for its TX path.

### 3.2 Fixed point

- Every signal's Q-format, rounding and saturation point is recorded in `docs/fixed-point.md`, including CIC bit growth.
- Rounding and saturation are explicit. Truncation is never silent.
- The Python bit-true model (§8.1) uses **exactly the same widths and rounding**, so comparisons are bit-exact wherever the design allows.

### 3.3 DDC

- **NCO:** phase accumulator plus a quarter-wave sine/cosine LUT, or a CORDIC. ADR, with measured SFDR.
- **Mixer:** complex multiply on DSP48E1. Check in the synthesis report that multipliers land in DSPs, not LUTs.
- **Decimation:** CIC ÷4 (state the order and bit growth), then a compensation FIR for CIC droop.
- **Clock budget:** the core clock is ~100× the input sample rate. Time-multiplexing is allowed, but clarity comes first; the 100T has area to spare.
- **Bring-up:** preload a short IQ snippet into BRAM as a ROM. That gets the DDC working without Ethernet or DDR3. A full pass streams from the host. DDR3 (MIG) is only needed if replay must decouple from the host.

### 3.4 Synchronization

- **Timing:** Gardner needs ≥ 2 samples/symbol, and 3.56 isn't an integer, so a Farrow cubic interpolator resamples to 2 sps.
  - **OQPSK caveat:** with Q staggered by T/2, a plain QPSK Gardner sees the Q rail at the wrong instants. Either delay I by T/2 (a fractional delay at 3.56 sps) **before** the TED, or use an OQPSK-aware TED where Q's strobes are I's midpoints. ADR, with lock behaviour from the model.
  - The loop filter is PI. Document bandwidth and damping.
- **OQPSK alignment:** at 2 sps, delaying I by exactly one sample aligns the rails. From there the signal is treated as QPSK for carrier recovery and decisions.
- **Carrier:** Costas loop with a second-order PI filter. It must track the ±3.4 kHz Doppler sweep plus the TCXO offset. **Document lock range and measured lock time.**
- **AGC:** normalize amplitude before soft-symbol quantization, so loop gains and soft-bit scaling don't depend on signal strength.

### 3.5 Frame sync and phase ambiguity

- The ASM is convolutionally encoded along with the data. The receiver therefore **correlates soft symbols against the encoded ASM pattern** under every phase hypothesis: 4 rotations, plus I/Q swap if Phase 0 says it's needed. The winner gives both the frame position and the derotation.
- **Exclude the first 12 encoded symbols** of the pattern. They depend on the previous frame's last 6 bits.
- **Sync FSM:** SEARCH → VERIFY → LOCK, with configurable thresholds and a flywheel (lose lock after N consecutive misses).
- After Viterbi, confirm the plain ASM every 1,024 bytes.

### 3.6 Viterbi — the centerpiece

The full tradeoff analysis goes in `docs/viterbi.md`, with an ADR per row:

| Component | Decision |
|---|---|
| Branch metrics | 3-bit vs. 4-bit soft quantization: coding gain vs. area. **Measure both.** |
| ACS | **Fully parallel, 64 states.** The 100T has the area, and it's simpler and faster than folding. |
| Path metrics | Modulo arithmetic vs. subtract-minimum normalization. Prove no overflow (§8.3). |
| Survivors | Traceback memory (BRAM) vs. register exchange |
| Traceback depth | Configurable, 5–7 × K (35–50). **Sweep it and plot BER vs. depth.** |
| Throughput | Coded symbols/s achieved vs. the 144 k/s needed. Report the headroom. It also sets the maximum BER-campaign replay speed. |

### 3.7 Reed-Solomon

- **Parameterized** over `M` (symbol bits), `PRIM_POLY`, `FCR` (first consecutive root), `PRIM` (root spacing), `NROOTS`, `N` and `K`, with shortened codes supported. **No hardcoded GF(2⁸) logic.** The same block must instantiate as RS(544,514) over GF(2¹⁰) without code changes.
- **Pipeline:** syndromes (Horner) → Berlekamp–Massey (inversionless preferred) → Chien search → Forney → correction.
- **Interleave:** four decoder instances, or one time-multiplexed. ADR.
- **Outputs:** corrected symbols per codeword and an uncorrectable flag.
- If Phase 0 finds dual-basis representation, convert at the decoder's input and output.

**Reed-Solomon reuse contract (Project 4 uses this decoder for KP4 FEC):**
- Lives in its own repo, `fpga-rs-core`, as a submodule (like fpga-eth-core).
- Parameters: symbol width m, n (including shortened codes, n < 2^m − 1), k,
  field polynomial, first consecutive root, root step.
  - CCSDS: m=8, RS(255,223), poly x⁸+x⁷+x²+x+1, roots α^(11j) for j=112..143
    (first root 112, step 11).
  - KP4:   m=10, RS(544,514), poly x¹⁰+x³+1, roots α^j for j=0..29
    (first root 0, step 1), shortened.
- Basis conversion (dual ↔ conventional) and interleaving (CCSDS depth 4) are
  wrappers outside the decoder.
- **Fully pipelined: accepts one symbol per clock with no stalls between codewords**
  (syndromes of codeword N+1 overlap Berlekamp-Massey/Chien/Forney of codeword N).
  CCSDS doesn't need this; Project 4 does.
- **Verify both parameter sets in this project.** The cocotb suite runs CCSDS AND
  KP4 vectors (random codewords with 0..t errors, and t+1 to check failure detection),
  generated by an independent Python reference. Project 4 then inherits a decoder
  already proven at its parameters.

### 3.8 Debug

- ILA builds sit behind a flag: `make impl ILA=1`. Functional builds never depend on debug cores.
- A debug tap streams decimated soft symbols to the host, for `gs-view`'s live constellation and for the constellation GIF.

---

## 4. C++ ground station (`gs/`)

```
 .iq ──▶ gs-replay ──UDP──▶ [FPGA] ──UDP──▶ gs-rx ──▶ cadus.bin, packets/
                                              ├──▶ gs-diff  (vs. SatDump)
                                              └──▶ gs-view  (live status)
```

| Tool | Does |
|---|---|
| `gs-replay` | Reads `.iq`, packetizes into UDP with sequence numbers, paces at real time, at N× real time, or flat out. Logs the achieved rate on every run. Also replays BER-campaign files into the injection mux (§8.4). |
| `gs-rx` | Network thread → **lock-free SPSC ring buffer** → processing thread. Parses VCDU and M_PDU headers, demuxes virtual channels, extracts CCSDS space packets. |
| `gs-diff` | Bit-exact CADU comparison against SatDump's decode of the same recording. Reports the first divergence (frame, byte, bit) and totals. |
| `gs-view` | Terminal UI: sync state, frame and packet counts, FER, Viterbi and RS corrections, live constellation from the debug tap |
| *Optional:* image reconstruction | MSU-MR packets → PNG, compared to SatDump's image. It's a JPEG-style decoder, so do it last. |

Write `gs-replay` during Phase B; the hardware bring-up needs it.

---

## 6. Toolchain and build process (planned targets and CI)

The current targets and rules are in CLAUDE.md §6. This is the full planned set from the original spec, including
targets not implemented yet.

| Tool | Use |
|---|---|
| Vivado ML Standard (batch Tcl) | Synthesis, implementation, ILA |
| Verilator | Lint, simulation |
| cocotb + cocotb-coverage | Testbenches, coverage |
| SymbiYosys | Formal on small blocks (§8.3) |
| Python 3 (NumPy, SciPy, matplotlib, pytest) | Golden model, BER campaigns, plots |
| C++20, CMake, GoogleTest, clang-tidy, cppcheck, libFuzzer | Ground station |
| SatDump (stable release, not V2 alpha) | Pass prediction, capture, **golden decoder** |
| `rtl_sdr` / librtlsdr | Raw IQ capture |

**Pin versions** of every tool in `docs/toolchain.md`. The Tcl scripts warn on a Vivado version mismatch.

### Makefile targets — all must work from a clean checkout

```
make setup         # .venv + pinned requirements.txt; git submodule update --init
make lint          # verilator --lint-only -Wall, zero warnings
make sim           # fast cocotb regression (< 5 min)
make sim-full      # long runs: full-pass sims, long BER sweeps in sim
make cov           # coverage report → docs/reports/coverage/
make formal        # SymbiYosys (§8.3)
make model-test    # pytest: golden model vs. CCSDS vectors and the committed IQ snippet
make gs            # cmake build of ground-station tools (Release + Debug/ASan/UBSan)
make gs-test       # GoogleTest
make fuzz          # libFuzzer on the packet parser (time-boxed in CI)
make synth impl prog
make reports       # copy timing + utilization into docs/reports/<tag>/
make ber           # BER campaign (sim or hardware, §8.4)
make plots         # regenerate every plot from data/results/
make ci            # everything CI runs, locally
make clean
```

- **Vivado runs in batch mode** via `syn/` Tcl. No GUI-only steps.
- **Vivado isn't in hosted CI.** Run it locally and commit the timing and utilization reports for every tagged milestone.
- **Timing closure is required.** No milestone is tagged with negative slack.

### CI on every push

- `make lint sim formal model-test gs gs-test`
- a 60 s fuzz run
- clang-tidy, cppcheck and ruff clean

**A broken CI gets fixed before anything else.**

---

## 8. Verification

### 8.1 Models (`model/`)

1. **Algorithm model** (float NumPy, full chain): validated against SatDump on a public recording **before any RTL is written**.
2. **Bit-true model:** the same chain at RTL widths and rounding. This is the cocotb scoreboard reference.
3. **Channel model / modulator:** random frames → RS encode → interleave → randomize → conv-encode → OQPSK → RRC → AWGN at a set Eb/N₀, plus carrier offset, Doppler ramp, phase noise and timing offset.

### 8.2 cocotb

- **Per block:** bit-exact against the bit-true model. For loops, compare within tolerances that are defined and justified in the test.
- **Full chain:** the committed real IQ snippet must produce the same CADUs as SatDump.
- **Scenarios to cover:**
  - frequency offset and Doppler ramp; timing offset
  - every phase rotation and I/Q swap
  - sync loss and reacquisition
  - frames at the RS correction limit (16 symbol errors) and just past it (17)
  - all-zero and all-one payloads
  - replay packet gaps
  - backpressure at every interface
- **Coverage bins:**
  - sync FSM states and transitions
  - each phase hypothesis winning
  - RS errors 0–16 plus uncorrectable
  - loop lock states
  - Viterbi normalization events
  - backpressure per interface

  **Coverage closure means 100% of defined bins**, with a written justification for any exclusion.

### 8.3 Formal (SymbiYosys)

- AXI-Stream handshake properties on block boundaries
- The sync FSM
- Viterbi path-metric normalization: no overflow
- The RS syndrome block on small parameter sets

### 8.4 BER campaigns: hardware-accelerated

- Python generates frames with known payloads at each Eb/N₀ point and writes them as IQ files.
- **Run them on the FPGA through `gs-replay`.** Simulation can't reach 10⁻⁶ BER in reasonable time; the hardware can.
- **Throughput cap:** flat-out replay is ~90 Mb/s, about 5.5× real time at 1.024 MS/s. For speed, generate campaign files at the RRC input rate (256 kS/s) and use the **injection mux** at the RRC input. That bypasses the DDC and gives roughly 4× more headroom. The DDC is verified separately.
- **Statistical rule:** at least 100 bit errors per point. Otherwise report the point as an upper bound.
- **Plot** on the same axes: uncoded OQPSK (theory Q(√(2Eb/N₀))), Viterbi only, Viterbi + RS, theory, and the model curve. Label pre-/post-FEC explicitly. Report the coding gain at 10⁻⁵. Reference point: soft-decision K=7 r½ Viterbi reaches ~10⁻⁵ near 4.4 dB.

### 8.5 Real-pass validation

- Every recording is decoded by SatDump **first**.
- `gs-diff` against SatDump's CADUs is the acceptance test, targeting 100% bit-exact on frames both decoders produce.
- Explain frames that only one side decodes. Usually they sit at the edges of the pass.

---

## 9. Phases and definitions of done

Every phase's DoD includes:
- README updated
- `docs/log.md` entry written
- that phase's media captured (§11.1)
- the user confirming the physical captures

### Phase 0 — Signal spec + capture kit
- [ ] `docs/signal-spec.md` written from SatDump's M2-x 72k pipeline and source, with file/commit citations:
  - RRC roll-off
  - differential coding
  - I/Q swap
  - conv output order and inversion
  - RS basis
- [ ] A public M2-x 72k recording decoded with SatDump, before buying anything
- [ ] Kit bought; **one pass of your own captured at 1.024 MS/s and decoded with SatDump**
- [ ] Media: antenna setup photo; SatDump waterfall during the pass; SatDump's decoded image

### Phase A — Python golden model
- [ ] Algorithm model reproduces SatDump's CADUs on the public recording and on your own
- [ ] Modulator + AWGN generator; model BER curves match theory
- [ ] Bit-true version defined; `fixed-point.md` started
- [ ] Media: model constellation before and after carrier lock

### Phase B — DDC
- [ ] Ingest conversion, NCO, mixer, CIC, compensation FIR; bit-exact against the model
- [ ] `gs-replay` written
- [ ] On hardware: first from the BRAM ROM, then over Ethernet from `gs-replay`
- [ ] Media: spectrum before and after DDC (plot); ILA capture of baseband I/Q

### Phase C — Synchronization
- [ ] RRC, Farrow + Gardner (OQPSK approach per ADR), OQPSK alignment, Costas, AGC
- [ ] Locks on synthetic signals with a Doppler ramp; lock time and lock range measured
- [ ] Locks on the real recording
- [ ] Media:
  - **animated constellation GIF**: spinning ring → four clean clusters as the loop locks
  - lock-time plot
  - Doppler-tracking plot

### Phase D — Viterbi + frame sync
- [ ] Built incrementally: branch metrics → one ACS → full ACS array → traceback, each step tested against the model
- [ ] Encoded-ASM correlator with phase resolution; sync FSM
- [ ] BER after Viterbi matches the model's curve
- [ ] 3-bit vs. 4-bit soft-decision comparison measured; traceback-depth sweep
- [ ] Media: BER plot (Viterbi vs. theory); ILA capture of path metrics; waveform of ACS/traceback

### Phase E — RS + integration + real decode
- [ ] Parameterized RS decoder, ASM check, derandomizer, full chain
- [ ] RS block also instantiated as RS(544,514)/GF(2¹⁰) in a unit test, proving the parameterization is real
- [ ] **A real pass decoded on the FPGA, with CADUs matching SatDump bit-for-bit**
- [ ] Full hardware BER campaign: uncoded, Viterbi, Viterbi + RS
- [ ] Timing closed; per-block utilization recorded
- [ ] Media: real-decode stats; full BER plot; Vivado device view

### Phase F — C++ ground station
- [ ] `gs-rx`, `gs-diff`, `gs-view`; CI green including static analysis, sanitizers and fuzzing
- [ ] **Definition of done:** a recorded Meteor pass replays through the Arty and comes out as space packets matching SatDump bit-for-bit
- [ ] Optional: image reconstructed from your own decoded packets
- [ ] Media: `gs-view` asciinema during a live replay; **hero image** (§11.1); **demo video**

---

## 10. Out of scope — do not build

- Transmit path
- LDPC/turbo codes
- CCSDS SLE and anything past the space-packet layer, except the optional image reconstruction
- Live RF into the FPGA (RF ADC hardware)
- 80k interleaved mode, unless the satellite stays in 80k
- GOES HRIT or other satellites
- **Cut order if descoping:** RS first, then the derandomizer. DDC → sync → Viterbi is the core and survives any descope.

---

## 11. Portfolio deliverables — mandatory

### 11.1 What to capture

Claude generates plots and terminal recordings itself. For photos, phone video and anything involving the antenna or board, **Claude lists exactly what to capture at the end of each phase, adds it to `docs/portfolio-todo.md`, and waits for the user**.

| Capture | Type | Phase |
|---|---|---|
| **Hero image:** Meteor imagery decoded by *your* FPGA receiver, next to SatDump's from the same pass | Image | E/F |
| **Hero GIF:** constellation locking (ring → 4 clusters) | GIF from debug-tap/model data | C |
| **Demo video (60–120 s):** antenna and pass capture (time-lapse), replay into the board, `gs-view` live, final image reveal | Phone + OBS, unlisted YouTube | F |
| Antenna setup photo; SatDump waterfall of your pass | Photo, screenshot | 0 |
| Spectrum before/after DDC | Plot | B |
| Lock-time and Doppler-tracking plots | Plot | C |
| BER vs. Eb/N₀: uncoded, Viterbi, Viterbi + RS, vs. theory | Plot | D/E |
| BER vs. traceback depth; 3-bit vs. 4-bit soft decision | Plot | D |
| ILA captures: baseband I/Q, Viterbi path metrics | Screenshots | B/D |
| Vivado device view + per-block utilization | Screenshot + table | E |
| `gs-diff` result: "N CADUs, 0 differences vs. SatDump" | asciinema / GIF | E/F |

### 11.2 Media rules

- Files live in `docs/media/`, named `YYYY-MM-DD_phase-x_description.ext`.
- **Plots are generated by `make plots` from `data/results/`.**
  - Reproducible and never hand-edited.
  - One consistent style; axes labeled with units.
- Every result in `data/results/` has a sidecar `.md` with: commit hash, exact command, tool versions, input recording (MANIFEST entry) or seed, and an interpretation paragraph.
- GIFs stay ≤ 8 MB in the repo. Videos go to unlisted YouTube or GitHub attachments, linked from the README, never committed.
- Screenshots are cropped to the point and annotated where it isn't obvious.

### 11.3 Lab notebook — `docs/log.md`

- **Each entry:** dated, with what was done and the numbers measured.
- **Bugs:** written as **symptom → root cause → fix**.
- **Passes:** each one captured, with date, max elevation and outcome.
- **These entries are interview material.** Claude appends one at the end of every session.

### 11.4 README standard



The README is a technical project report, not a summary. Use the RISC-V core's README
(github.com/RodeanAzari/riscv-rv32i-tmr-core) as the template for structure, depth and tone.
Every number comes from a committed report or CSV produced by a `make` target and links
to it; anything unmeasured is a dash or `[TBD]`, never an estimate. Sections, in order:

**At a glance table:** directly under the intro and hero image, the README has a two-column
table (`| | |`) of 10–15 rows that summarizes the whole project for someone who reads nothing
else. Each row is a short label and a short measured fact with its condition
(e.g. "p99 latency | 312 ns, 1M events, 125 MHz core"). Every value comes from a committed
report and matches the full Results section. Unmeasured rows show `[TBD]` until measured.
Keep it current at the end of every phase.

Rows: Target signal (Meteor-M N2-4, 72k OQPSK) · Receive chain · Real passes decoded ·
CADU match vs. SatDump · Coding gain at BER 10⁻⁵ · Viterbi throughput and headroom ·
Lock time / Doppler range tracked · Formal proofs · Bugs caught · Fmax ·
Utilization per block · Ground-station tools + CI checks

1. **Title that states the claim**, then an intro paragraph with the headline numbers,
   a status line, a sourcing note ("every number comes from `docs/reports/`, produced by
   `make …`"), and a hero image or GIF with a caption.
2. **At a glance**: a two-column table of the key facts and metrics.
3. **Status**: the phase table, linking to `docs/design.md` and `docs/log.md`.
4. **Architecture**: a Mermaid diagram plus bullets on clocking, CDC, interfaces and data flow.
5. **Verification, by layer**: formal (properties proven, depth), cocotb (tests passed,
   events checked against the golden model, coverage bins hit), hardware (ILA captures
   checked by script). Include a **numbered list of bugs found**, each with how it was found
   and which layer caught it, and any bugs planted to prove the testbench catches them.
6. **One deep section per major block**: what it does, the design alternatives in a
   comparison table (resources, latency, Fmax), which one was chosen and why, and how it
   was verified.
7. **On the board**: photos, ILA captures with a sample-by-sample table explaining what
   the waveform shows, real terminal output in code blocks.
8. **Demos**: embedded video, the commands to reproduce them, and a table of each demo
   with its on-board result.
9. **In Vivado**: a captioned screenshot grid (device view, worst path, timing,
   utilization, schematic, power) for each major build.
10. **Results**: tables where every row links to its report file, with measurement
    conditions stated (clock, data set, run length).
11. **Limitations**: a candid bulleted list of what the design doesn't do, what's
    optimistic about the numbers, and what's untested.
12. **Build and reproduce**: prerequisites with versions, a table of every `make` target,
    and what runs in CI vs. locally.
13. **Repository layout** table, then **Roadmap**.

Tone: precise, numbers always carry their conditions, no marketing language, failures and
limits stated openly. Update the README at the end of every phase. A phase isn't done
until its section is written to this standard.

Deep sections: DDC, timing/carrier recovery, frame sync and phase ambiguity, Viterbi, Reed-Solomon, ground station. Hero: your decoded Meteor image next to SatDump’s. Limitation #1: recorded rather than live RF.

