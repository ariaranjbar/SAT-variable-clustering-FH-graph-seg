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

Use the Python runner to sweep algorithms across random CNF inputs and append metrics to CSVs in `scripts/benchmarks/out/`.

Quick examples (after building):

```bash
python3 scripts/benchmarks/bench_runner.py vig_info -n 5 \
  --implementations naive,opt --taus 3,5,10,inf --threads 1,2,4 --maxbufs 50000000,100000000 \
  --skip-existing -v

python3 scripts/benchmarks/bench_runner.py segmentation -n 5 \
  --implementations naive,opt --taus 3,5,10,inf --ks 25,50,100 --threads 1,2,4 --maxbufs 50000000,100000000 \
  --skip-existing -v
```

You can also run batch configs:

```bash
scripts/benchmarks/bench_runner.py config --file scripts/benchmarks/configs/example_configs.json -v
```

Algorithms are defined once in `scripts/benchmarks/configs/algorithms.json` (binary discovery, command template, validated parameters, CSV schema). This allows adding new tools or tweaking mappings without changing Python code. Legacy bash helpers remain available; see `scripts/benchmarks/README.md` for details.
