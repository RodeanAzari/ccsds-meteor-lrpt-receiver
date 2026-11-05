PY := .venv/bin/python
RTL := $(shell find rtl -name '*.sv' -not -path 'rtl/eth/*' | sort)
RTL_DIRS := $(sort $(dir $(RTL)))

.PHONY: setup model-test check-spec lint lint-py sim ddc-rtl-results sync-rtl-results synth-ooc board prog board-check ila-capture ber sync-study ddc-study rrc-study sync-fixed-study soft-width-study traceback-study plots synthetic-iq gs-replay-results gs-lint ci clean \
        sim-full cov formal gs gs-test fuzz synth impl reports

setup:
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

# Zero Verilator -Wall warnings, each module linted as its own top (CLAUDE.md §5.1).
lint:
	@for f in $(RTL); do echo "lint $$f"; verilator --lint-only -Wall $(addprefix -y ,$(RTL_DIRS)) $$f || exit 1; done

# cocotb regression, bit-exact against the bit-true model (CLAUDE.md §8.2).
sim:
	$(PY) tb/cocotb/run.py

# Record the DDC RTL's bit-exactness and throughput in data/results/ddc_rtl_sim.csv.
ddc-rtl-results:
	WRITE_RESULTS=1 $(PY) tb/cocotb/run.py test_ddc_top

# Record the sync RTL's bit-exactness and throughput in data/results/{rrc,agc,costas,timing}_rtl_sim.csv.
sync-rtl-results:
	WRITE_RESULTS=1 $(PY) tb/cocotb/run.py test_sync_rrc test_sync_agc test_sync_costas test_sync_timing

# Out-of-context synth + place + route of one block at 100 MHz (CLAUDE.md §6). Reports: docs/reports/ooc/$(TOP)/.
TOP ?= ddc_top
synth-ooc:
	mkdir -p build/syn && cd build/syn && ../../scripts/vivado.sh -mode batch -source ../../syn/synth_ooc.tcl \
		-tclargs $(TOP) > $(TOP).log 2>&1 || { tail -30 $(TOP).log; exit 1; }
	@grep "^OOC " build/syn/$(TOP).log
	$(PY) -m analysis.synth_report $(TOP)

# Phase B board bring-up: ROM snippet -> DDC -> UART (rtl/top/arty_ddc_rom_top.sv). `make board prog board-check`.
BOARD_TOP := arty_ddc_rom_top
SERIAL ?= /dev/ttyUSB1
ILA ?= 0
BOARD_NAME := $(BOARD_TOP)$(if $(filter 1,$(ILA)),_ila)
board:
	PYTHONPATH=. $(PY) scripts/ddc_board.py rom build/board/rom/iq_rom.mem
	cd build/board && ../../scripts/vivado.sh -mode batch -source ../../syn/impl_board.tcl \
		-tclargs $(BOARD_TOP) rom/iq_rom.mem $(if $(filter 1,$(ILA)),ila) > $(BOARD_NAME).log 2>&1 \
		|| { tail -30 $(BOARD_NAME).log; exit 1; }
	@grep "^BOARD " build/board/$(BOARD_NAME).log
	$(PY) -m analysis.synth_report $(BOARD_NAME) board

# Claim the shared board first: python3 ~/fpga-coord/coord.py board claim P3 "<reason>" (fpga-coord PROTOCOL §6)
prog:
	openFPGALoader -b arty_a7_100t build/board/$(BOARD_TOP).bit

board-check:
	PYTHONPATH=. $(PY) scripts/ddc_board.py check $(SERIAL)

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
ci: lint-py lint model-test sim gs-test gs-lint

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache build sim_build

# Fail loudly instead of pretending these work.
sim-full cov formal fuzz synth impl reports:
	@echo "make $@: not implemented yet (needs RTL or C++ from a later phase)" >&2; exit 1
