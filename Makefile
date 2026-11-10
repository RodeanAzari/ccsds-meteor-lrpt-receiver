PY := .venv/bin/python
RTL := $(shell find rtl -name '*.sv' -not -path 'rtl/eth/*' -not -path 'rtl/rs/*' | sort)
# rtl/eth, rtl/rs (fpga-eth-core, fpga-rs-core at their tags; linted in their own repos) and tb/models
# (vendor-primitive stand-ins) resolve instances only.
RTL_DIRS := $(sort $(dir $(RTL))) rtl/eth/rtl/ rtl/rs/rtl/ tb/models/

.PHONY: setup model-test check-spec lint lint-py sim ddc-rtl-results sync-rtl-results fec-rtl-results rx-top-rtl-results synth-ooc board prog board-check eth-check rx-check ila-capture ber sync-study ddc-study rrc-study sync-fixed-study soft-width-study traceback-study sync-lock-study framesync-study plots synthetic-iq gs-replay-results gs-lint ci clean \
        sim-slow sim-full cov formal gs gs-test fuzz synth impl reports

setup:
	git submodule update --init
	python3 -m venv .venv
	$(PY) -m pip install -q -r requirements.txt

check-spec:
	$(PY) scripts/verify_signal_spec.py

model-test: check-spec
	PYTHONPATH=. $(PY) scripts/gen_rtl_tables.py --check
	$(PY) -m pytest -q

lint-py:
	$(PY) -m ruff check model analysis scripts tb gs/tests
	$(PY) -m mypy

ber:
	$(PY) -m analysis.ber

sync-study:
	$(PY) -m analysis.sync_study

ddc-study:
	$(PY) -m analysis.ddc_fixed_study

rrc-study:
	$(PY) -m analysis.rrc_fixed_study

sync-fixed-study:
	$(PY) -m analysis.sync_fixed_study

soft-width-study:
	$(PY) -m analysis.soft_width_study

traceback-study:
	$(PY) -m analysis.traceback_study

sync-lock-study:
	$(PY) -m analysis.sync_lock_study

framesync-study:
	$(PY) -m analysis.framesync_study

# Zero Verilator -Wall warnings, each module linted as its own top (CLAUDE.md §5.1).
lint:
	@for f in $(RTL); do echo "lint $$f"; verilator --lint-only -Wall $(addprefix -y ,$(RTL_DIRS)) $$f || exit 1; done

# cocotb regression, bit-exact against the bit-true model (CLAUDE.md §8.2).
sim:
	$(PY) tb/cocotb/run.py

# The slowest unit tests (tb/cocotb/run.py SLOW), kept out of make sim's 5-minute budget but run by make ci.
sim-slow:
	$(PY) tb/cocotb/run.py --slow

# Long runs (CLAUDE.md §6): the sync chain's output decoded end to end (~4 min), and the chain through the Viterbi
# (~10 min). Results: make sync-rtl-results, make fec-rtl-results.
sim-full:
	$(PY) tb/cocotb/run.py --full

# Record the DDC RTL's bit-exactness and throughput in data/results/ddc_rtl_sim.csv.
ddc-rtl-results:
	WRITE_RESULTS=1 $(PY) tb/cocotb/run.py test_ddc_top

# Record the sync RTL's bit-exactness and throughput in data/results/{rrc,agc,costas,timing,sync_top}_rtl_sim.csv
# and the end-to-end decode in sync_chain_rtl_decode.csv (includes the sim-full run, ~4 min).
sync-rtl-results:
	WRITE_RESULTS=1 $(PY) tb/cocotb/run.py test_sync_rrc test_sync_agc test_sync_costas test_sync_timing test_sync_top \
		test_sync_top_full

# Record the Viterbi RTL's bit-exactness and throughput in data/results/viterbi_rtl_sim.csv, the frame sync's in
# framesync_rtl_sim.csv, and the chain through the Viterbi in rx_chain_rtl_decode.csv (includes the sim-full run).
fec-rtl-results:
	WRITE_RESULTS=1 $(PY) tb/cocotb/run.py test_fec_viterbi test_fec_framesync test_rx_chain_full

# The board top (arty_rx_eth_top) from MII in to CADU packets out, in rx_top_rtl_decode.csv (a sim-full run, ~5 min).
rx-top-rtl-results:
	WRITE_RESULTS=1 $(PY) tb/cocotb/run.py test_arty_rx_eth_top_full

# Out-of-context synth + place + route of one block at 100 MHz (CLAUDE.md §6). Reports: docs/reports/ooc/$(TOP)/.
TOP ?= ddc_top
# Optional: GENERICS="NAME=VALUE ..." parameter overrides, NAME=<result name> (default TOP) for such a variant.
# Not ?=: WSL exports NAME (the hostname), which must not rename the report. NAME=... on the command line still wins.
synth-ooc: NAME = $(TOP)
synth-ooc:
	mkdir -p build/syn && cd build/syn && OOC_GENERICS="$(GENERICS)" OOC_NAME="$(NAME)" ../../scripts/vivado.sh \
		-mode batch -source ../../syn/synth_ooc.tcl -tclargs $(TOP) > $(NAME).log 2>&1 || { tail -30 $(NAME).log; exit 1; }
	@grep "^OOC " build/syn/$(NAME).log
	$(PY) -m analysis.synth_report $(NAME)

# Phase B board bring-up: ROM snippet -> DDC -> UART (rtl/top/arty_ddc_rom_top.sv). `make board prog board-check`.
# BOARD_TOP=arty_ddc_eth_top: the same DDC fed over Ethernet by gs-replay (no ILA variant); see `make eth-check`.
# BOARD_TOP=arty_rx_eth_top: the whole receiver; the host sets the NCO word per replay (SET_NCO, ADR 0014).
BOARD_TOP ?= arty_ddc_rom_top
SERIAL ?= /dev/ttyUSB1
ILA ?= 0
BOARD_NAME := $(BOARD_TOP)$(if $(filter 1,$(ILA)),_ila)$(BOARD_SUFFIX)
BOARD_ROM := $(if $(findstring _eth_,$(BOARD_TOP)),none,rom/iq_rom.mem)
board:
	PYTHONPATH=. $(PY) scripts/ddc_board.py rom build/board/rom/iq_rom.mem
	cd build/board && BOARD_GENERICS="$(BOARD_GENERICS)" BOARD_SUFFIX="$(BOARD_SUFFIX)" ../../scripts/vivado.sh -mode batch -source ../../syn/impl_board.tcl \
		-tclargs $(BOARD_TOP) $(BOARD_ROM) $(if $(filter 1,$(ILA)),ila) > $(BOARD_NAME).log 2>&1 \
		|| { tail -30 $(BOARD_NAME).log; exit 1; }
	@grep "^BOARD " build/board/$(BOARD_NAME).log
	$(PY) -m analysis.synth_report $(BOARD_NAME) board

# Claim the shared board first: python3 ~/fpga-coord/coord.py board claim P3 "<reason>" (fpga-coord PROTOCOL §6)
prog:
	openFPGALoader -b arty_a7_100t build/board/$(BOARD_TOP).bit

board-check:
	PYTHONPATH=. $(PY) scripts/ddc_board.py check $(SERIAL)

# After `make board BOARD_TOP=arty_ddc_eth_top prog` (and the board claim): stream the snippet with gs-replay and
# compare the dump. IFACE = the host's IP on the cable to the Arty; SPEED = times real time, comma list (one replay each).
IFACE ?=
SPEED ?= 1
eth-check: gs
	PYTHONPATH=. $(PY) scripts/ddc_board.py eth-check $(SERIAL) --iface $(IFACE) --speed $(SPEED) \
		--bit build/board/$(BOARD_TOP).bit

# After `make board BOARD_TOP=arty_rx_eth_top` (and the board claim): program, set the NCO word from REC's coarse
# estimate, replay REC, receive its CADUs and stats, compare with TRUTH. One replay per SPEED.
REC ?= data/synthetic/synthetic_seed2026_1024000SPS.cu8
TRUTH ?= data/synthetic/synthetic_seed2026_truth.cadu
rx-check: gs
	PYTHONPATH=. $(PY) scripts/board_rx.py check $(REC) $(TRUTH) --iface $(IFACE) --speed $(SPEED) \
		--bit build/board/arty_rx_eth_top.bit

# After `make board ILA=1` (and the board claim): program, capture every DDC output with the ILA, compare.
ila-capture:
	cd build/board && ../../scripts/vivado.sh -mode batch -source ../../syn/ila_capture.tcl -tclargs \
		$(CURDIR)/build/board/$(BOARD_TOP)_ila.bit $(CURDIR)/build/board/$(BOARD_TOP)_ila.ltx \
		$(CURDIR)/build/board/ila_ddc.csv $(SERIAL) $(CURDIR)/$(PY) > ila_capture.log 2>&1 \
		|| { tail -30 ila_capture.log; exit 1; }
	PYTHONPATH=. $(PY) scripts/ddc_board.py ila-check build/board/ila_ddc.csv

plots:
	$(PY) -m analysis.plots

synthetic-iq:
	PYTHONPATH=. $(PY) scripts/make_synthetic_iq.py

# Ground station (CLAUDE.md §4): Release + Debug with ASan/UBSan.
gs:
	cmake -S gs -B build/gs-Release -DCMAKE_BUILD_TYPE=Release
	cmake --build build/gs-Release -j
	cmake -S gs -B build/gs-Debug -DCMAKE_BUILD_TYPE=Debug
	cmake --build build/gs-Debug -j

# GoogleTest in both builds, then the gs-replay loopback test against the sanitized binary.
gs-test: gs
	cd build/gs-Release && ctest --output-on-failure
	cd build/gs-Debug && ctest --output-on-failure
	GS_REPLAY=build/gs-Debug/gs-replay $(PY) -m pytest -q gs/tests

# C++ static analysis (CLAUDE.md §5.3): format check, clang-tidy (gs/.clang-tidy, warnings are errors), cppcheck.
# cppcheck skips gs/tests: clang-tidy covers them, and cppcheck misreads GoogleTest's macros.
GS_SRC := $(wildcard gs/src/*.cpp gs/include/gs/*.hpp gs/tests/*.cpp)
gs-lint: gs
	clang-format --style=file:gs/.clang-format --dry-run -Werror $(GS_SRC)
	clang-tidy -p build/gs-Release --quiet $(filter %.cpp,$(GS_SRC))
	cppcheck --std=c++20 --enable=warning,style,performance,portability --inline-suppr --error-exitcode=1 \
		--suppress=missingIncludeSystem -I gs/include --quiet gs/src gs/include

gs-replay-results: gs
	PYTHONPATH=. $(PY) scripts/gs_replay_results.py

# Only what exists so far. Grows with each phase.
ci: lint-py lint model-test sim sim-slow gs-test gs-lint

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache build sim_build

# SymbiYosys (buildplan §8.3), ~12 min: the path-metric hold proof and 8-step bounded check (tb/formal/
# fec_acs_array.sby; its unbounded task, step, is open and run by hand). Run directories and log in build/formal/.
formal:
	@mkdir -p build/formal
	cd tb/formal && sby -f --prefix ../../build/formal/fec_acs_array fec_acs_array.sby hold bmc4 \
		> ../../build/formal/fec_acs_array.log 2>&1 || { grep -E 'summary|DONE|ERROR' ../../build/formal/fec_acs_array.log | tail -20; exit 1; }
	@grep -E 'DONE' build/formal/fec_acs_array.log

# Fail loudly instead of pretending these work.
cov fuzz synth impl reports:
	@echo "make $@: not implemented yet (needs RTL or C++ from a later phase)" >&2; exit 1
