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
| clang-format, clang-tidy, cppcheck, libFuzzer (clang) | `[TBD]` | — | Not installed; no sudo in this session. Needed for CLAUDE.md §5.3 |
| SymbiYosys | `[TBD]` | — | Not checked |
| rtl_sdr | `[TBD]` | — | Not installed |
