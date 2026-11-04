"""Build and run the cocotb regression with Verilator: python tb/cocotb/run.py [test_module ...]"""

from __future__ import annotations

import sys
from pathlib import Path

from cocotb_tools.runner import get_results, get_runner

ROOT = Path(__file__).resolve().parents[2]

# test module -> (toplevel, sources, parameter sets)
NCO_LUT = {"LUT_FILE": f'"{ROOT / "rtl/ddc/nco_lut.mem"}"'}

TESTS: dict[str, tuple[str, list[str], list[dict[str, int | str]]]] = {
    "test_ddc_ingest": ("ddc_ingest", ["rtl/ddc/ddc_ingest.sv"], [{}]),
    "test_ddc_nco_mixer": ("ddc_nco_mixer", ["rtl/ddc/ddc_nco_mixer.sv"], [NCO_LUT]),
}


def main(names: list[str]) -> int:
    failed = 0
    # The tests import the bit-true model from the repo root. The runner builds the simulator's PYTHONPATH from
    # sys.path, so the paths go there. results.xml goes into the build directory.
    sys.path[:0] = [str(ROOT), str(ROOT / "tb" / "cocotb")]
    for name in names or list(TESTS):
        top, srcs, param_sets = TESTS[name]
        for params in param_sets:
            tag = "_".join(f"{k}{v}" for k, v in params.items() if isinstance(v, int)) or "default"
            build_dir = ROOT / "build" / "sim" / f"{name}_{tag}"
            runner = get_runner("verilator")
            runner.build(
                sources=[ROOT / s for s in srcs],
                hdl_toplevel=top,
                parameters=params,
                build_args=["--assert", "-Wall"],
                build_dir=build_dir,
                always=True,
            )
            results = runner.test(
                hdl_toplevel=top,
                test_module=name,
                test_dir=build_dir,
                build_dir=build_dir,
            )
            _, fails = get_results(results)
            failed += fails
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
