# Thesis Calculations (CMake C++ project)

Small C++ utilities for analyzing CNF benchmarks and derived graphs. Each algorithm is a standalone binary under `algorithms/` and links a common library in `src/common`.

## Layout

- `include/thesis/` — shared headers (CLI, timer, CNF, VIG)
- `src/common/` — shared implementations built as `thesis_common`
- `algorithms/` — per-tool binaries (e.g., `cnf_info`, `vig_info`)
- `benchmarks/` — CNF inputs (some `.xz` compressed)
- `scripts/benchmarks/` — runners and helpers
- `tests/` — CTest-based smoke tests

## Build

Works with CMake 3.16+ and C++20 on macOS/Linux/Windows.

Typical single-config build:

1) Configure: `cmake -S . -B build -DCMAKE_BUILD_TYPE=Release`
2) Build: `cmake --build build -j`

On multi-config generators (e.g., MSVC), pass `--config Release` to the build step and binaries will be under `build/algorithms/<name>/Release/`.

## Algorithms

- `cnf_info` — Prints basic info about a DIMACS CNF file and previews a few clauses.
   - Usage: `cnf_info --input <file.cnf|-> [--no-compact]`
   - Legacy: `cnf_info <file.cnf|-> [no-compact]`

- `vig_info` — Builds the Variable Interaction Graph (VIG) and reports summary stats.
   - Usage: `vig_info -i <file.cnf|-> [--tau N|inf] [--naive|--opt] [-t K] [--maxbuf M]`
   - Defaults: `--opt`, `--tau inf`, `-t 0(auto)`, `--maxbuf 50,000,000`

See per-algorithm READMEs under `algorithms/<name>/README.md` for details and examples.

## Tests

Run smoke tests with CTest after building:

`ctest --test-dir build --output-on-failure`

## Benchmarks

The script `scripts/benchmarks/run_vig_info_random.sh` runs `vig_info` across random CNF inputs, appending metrics to `scripts/benchmarks/out/results.csv`. It supports streaming decompression for `.xz` inputs and cleans up per-run logs on success (retains logs when failures occur or no summary is parsed). CSV uses `total_sec` as the runtime metric and may include component timings (`parse_sec`, `vig_build_sec`). See its README for usage.
