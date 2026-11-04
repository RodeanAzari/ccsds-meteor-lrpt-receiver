PY := .venv/bin/python
RTL := $(shell find rtl -name '*.sv' -not -path 'rtl/eth/*' | sort)
RTL_DIRS := $(sort $(dir $(RTL)))

.PHONY: setup model-test check-spec lint lint-py sim ddc-rtl-results ber sync-study ddc-study rrc-study sync-fixed-study soft-width-study traceback-study plots synthetic-iq ci clean \
        sim-full cov formal gs gs-test fuzz synth impl prog reports

setup:
	python3 -m venv .venv
	$(PY) -m pip install -q -r requirements.txt

check-spec:
	$(PY) scripts/verify_signal_spec.py

model-test: check-spec
	PYTHONPATH=. $(PY) scripts/gen_rtl_tables.py --check
	$(PY) -m pytest -q

lint-py:
	$(PY) -m ruff check model analysis scripts tb
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

plots:
	$(PY) -m analysis.plots

synthetic-iq:
	PYTHONPATH=. $(PY) scripts/make_synthetic_iq.py

# Only what exists so far. Grows with each phase.
ci: lint-py lint model-test sim

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache build sim_build

# Fail loudly instead of pretending these work.
sim-full cov formal gs gs-test fuzz synth impl prog reports:
	@echo "make $@: not implemented yet (needs RTL or C++ from a later phase)" >&2; exit 1
