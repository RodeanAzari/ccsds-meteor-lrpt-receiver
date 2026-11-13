# Toolchain

Versions marked "installed" were read from the machine on 2026-11-02. `[TBD]` means not installed or not yet checked.

| Tool | Version | Where | Status |
|---|---|---|---|
| SatDump | 1.2.2+gb79af48-2 (Ubuntu package). `docs/signal-spec.md` was read from commit `7aef0fe`, same version | WSL Ubuntu 26.04, `apt install satdump` | Installed 2026-11-03 |
| Verilator | 5.050 | WSL Ubuntu 26.04 | Installed |
| Python | 3.12.10 (Windows), 3.14.4 (WSL) | Both | Installed; project version `[TBD]` |
| Vivado | 2025.2 (build 6299465; edition not checked). `syn/synth_ooc.tcl` warns on any other version | `~/Xilinx/2025.2/Vivado`, run through `scripts/vivado.sh` (locale and ncurses workarounds; not on PATH) | Installed; OOC flow working 2026-11-04 |
| cocotb | 2.1.0 (pinned in `requirements.txt`) | `.venv` | Installed 2026-11-04 |
| tb-common (P2) | `tb-common-v0.1`, pip from git at the tag (`requirements.txt`) | `.venv` | Installed 2026-11-04 |
| pyserial | 3.5 (pinned in `requirements.txt`) | `.venv` | Installed 2026-11-04 |
| openFPGALoader | v1.1.1 (`make prog`) | `~/.local/opt/oss-cad-suite`; board attached to WSL with usbipd-win | Working 2026-11-04 |
| CMake | 4.2.3 | WSL Ubuntu 26.04 | Installed; `make gs` |
| g++ | 15.2.0 (C++20) | WSL Ubuntu 26.04 | Installed; `make gs` |
| GoogleTest | v1.15.2, fetched by CMake at a pinned SHA-256 (`gs/CMakeLists.txt`) | `build/gs-*/_deps` | Working 2026-11-04 |
| clang, clang-format, clang-tidy (libFuzzer ships with clang) | 21.1.8 (Ubuntu 21.1.8-6ubuntu1) | WSL Ubuntu 26.04, apt | Installed 2026-11-05; `make gs-lint`. libFuzzer: `make fuzz` (board packet parsers, space packet demux; 30 s each in `make ci`, 30 min weekly in `.github/workflows/fuzz-weekly.yml`); its runtime is apt `libclang-rt-dev`, not pulled in by `clang` without recommends |
| cppcheck | 2.19.0 | WSL Ubuntu 26.04, apt | Installed 2026-11-05; `make gs-lint` |
| SymbiYosys, Yosys, bitwuzla | SBY v0.69, Yosys 0.69+208, bitwuzla 0.9.1 | oss-cad-suite 20261007, `~/.local/opt/oss-cad-suite` | Working 2026-11-06; `make formal`. CI: weekly, `.github/workflows/formal-weekly.yml`, same build from GitHub |
| rtl_sdr, rtl_test, rtl_biast | rtl-sdr 2.0.2-2build1 (Ubuntu package). Its `rtl_sdr` has no `-T` bias-tee option: turn the bias tee on with `rtl_biast -b 1` | WSL Ubuntu 26.04, apt; dongle attached with usbipd-win | Installed 2026-11-13; device not yet tested |
