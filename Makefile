PY := .venv/bin/python

.PHONY: setup model-test check-spec lint-py ber sync-study ddc-study plots synthetic-iq ci clean \
        lint sim sim-full cov formal gs gs-test fuzz synth impl prog reports

setup:
	python3 -m venv .venv
	$(PY) -m pip install -q -r requirements.txt

check-spec:
	$(PY) scripts/verify_signal_spec.py

model-test: check-spec
	$(PY) -m pytest -q

lint-py:
	$(PY) -m ruff check model analysis scripts
	$(PY) -m mypy

ber:
	$(PY) -m analysis.ber

sync-study:
	$(PY) -m analysis.sync_study

ddc-study:
	$(PY) -m analysis.ddc_fixed_study

plots:
	$(PY) -m analysis.plots

synthetic-iq:
	PYTHONPATH=. $(PY) scripts/make_synthetic_iq.py

# Only what exists so far. Grows with each phase.
ci: lint-py model-test

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache build sim_build

# Fail loudly instead of pretending these work.
lint sim sim-full cov formal gs gs-test fuzz synth impl prog reports:
	@echo "make $@: not implemented yet (needs RTL or C++ from a later phase)" >&2; exit 1
