# thesis-code

Variable Incidence Graph (VIG) builders and CNF graph segmentation tools in modern C++ (C++20), plus reproducible benchmark runners.

This repository provides:

- A reusable C++ library (`thesis::common`) with CNF parsing, VIG construction (naive and optimized), graph segmentation, CLI, timer, CSV utilities, and compact component metrics.
- Three small executables built on top of the library:
  - `cnf_info` — parse a DIMACS CNF and print basic stats.
  - `vig_info` — build the Variable Incidence Graph (VIG) and print summary stats; can also dump the graph.
  - `segmentation` — build a VIG and segment it using a Felzenszwalb–Huttenlocher-style greedy merge; prints component metrics and can dump components/graph.
- Benchmark tooling (Python) to sweep parameters across large CNF corpora with CSV outputs.

## Quick start

Prerequisites:

- CMake ≥ 3.16
- A C++20 compiler (Clang 15+/AppleClang, GCC 10+, or MSVC 2019+)
- For benchmarks (optional): Python 3.9+, `xz` (for streaming `.xz` inputs), and optionally `pyyaml`

Build the project (Release):

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel
```

On Windows (multi-config generators):

```bash
cmake -S . -B build -G "Visual Studio 17 2022"
cmake --build build --config Release --parallel
```

Run a quick sanity check on the sample CNF:

```bash
# CNF info
build/algorithms/cnf_info/cnf_info algorithms/cnf_info/sample.cnf

# VIG summary (optimized builder)
build/algorithms/vig_info/vig_info -i algorithms/cnf_info/sample.cnf --tau 3 --opt -t 2

# Segmentation
build/algorithms/segmentation/segmentation -i algorithms/cnf_info/sample.cnf --tau 3 --k 50 --opt -t 2
```

Notes:

- When the input path is `-`, tools read from stdin (useful with `xz -dc file.cnf.xz | <tool> -i - ...`).
- On Windows with multi-config builds, binaries live under `build/algorithms/<tool>/Release/<tool>.exe`.

## Executables and usage

All tools share a lightweight, self-documented CLI (use `-h`/`--help`). Key options are summarized below.

### cnf_info

Print basic information about a DIMACS CNF and (optionally) disable parse-time normalizations.

```bash
cnf_info --input <file.cnf|-> [--no-compact] [--no-normalize]
```

Outputs (key=value on stdout): `vars, clauses, parse_sec, total_sec, compacted, normalized`.

### vig_info

Build the Variable Incidence Graph and print summary statistics.

```bash
vig_info -i <file.cnf|-> [--tau N|inf] [--naive|--opt] [-t K] [--maxbuf M] [--graph-out FILE]
```

- `--tau`: include only clauses of size ≤ tau (use `inf` for no limit)
- `--naive` or `--opt` (default) builder
- `-t/--threads` (opt only; `0` = auto)
- `--maxbuf` (opt only) capacity for batched contributions
- `--graph-out FILE` writes `FILE.node.csv` and `FILE.edges.csv`

Outputs: `vars, edges, parse_sec, vig_build_sec, total_sec, impl, tau, threads, agg_memory`.

### segmentation

Segment the VIG using a Felzenszwalb–Huttenlocher predicate with union–find.

```bash
segmentation -i <file.cnf|-> [--tau N|inf] [--k K] [--naive|--opt] [-t K] [--maxbuf M]
             [--graph-out FILE] [--comp-out DIR] [--comp-base NAME]
```

- `--k`: segmentation parameter (double); higher → fewer merges
- Optional outputs:
  - `--graph-out FILE` writes `FILE.node.csv` (`id,component`) and `FILE.edges.csv` (`u,v,w`)
  - `--comp-out DIR` and `--comp-base NAME` write `DIR/<base>_components.csv` with `component_id,size,min_internal_weight`

Outputs: `vars, edges, comps, k, tau, parse_sec, vig_build_sec, seg_sec, total_sec, impl, threads, agg_memory, keff, gini, pmax, entropyJ`.

## Benchmark runner (Python)

Use the dynamic runner to sweep algorithms over `benchmarks/` with CSV outputs in `scripts/benchmarks/out/`.

```bash
# VIG sweeps
python3 scripts/benchmarks/bench_runner.py vig_info -n 5 \
  --implementations naive,opt --taus 3,5,10,inf --threads 1,2,4 --maxbufs 50000000,100000000 \
  --skip-existing -v

# Segmentation sweeps
python3 scripts/benchmarks/bench_runner.py segmentation -n 5 \
  --implementations naive,opt --taus 3,5,10,inf --ks 25,50,100 --threads 1,2,4 --maxbufs 50000000,100000000 \
  --skip-existing -v
```

Features:

- Registry-driven subcommands in `scripts/benchmarks/configs/algorithms.json` (binary discovery, command templates, parameter schema/validation, CSV mapping).
- Streaming decompression of `.xz` inputs (requires `xz`).
- Optional per-file caching of decompressed inputs.
- Skip-existing runs based on CSV key columns; keeps logs only on failures.
- Config mode to run multiple algorithms from a JSON/YAML file:

```bash
python3 scripts/benchmarks/bench_runner.py config --file scripts/benchmarks/configs/example_configs.json -v
```

Environment (optional):

```bash
# Create a Python env with deps
conda env create -f scripts/benchmarks/environment.yml
conda activate thesis-bench
```

## Library overview

Headers live under `include/thesis/`, sources under `src/common/`:

- `thesis/cnf.hpp`: DIMACS CNF parser with optional variable compaction and clause normalization.
- `thesis/vig.hpp`: VIG API. `build_vig_naive` (single-threaded) and `build_vig_optimized` (multi-threaded, memory-aware).
- `thesis/segmentation.hpp`: Felzenszwalb–Huttenlocher-style graph segmenter using union–find.
- `thesis/disjoint_set.hpp`: Union–find with union-by-rank and path compression.
- `thesis/comp_metrics.hpp`: Compact metrics for component-size distributions (keff, Gini, pmax, entropy evenness).
- `thesis/cli.hpp`: Lightweight CLI parser used by the executables.
- `thesis/timer.hpp`, `thesis/csv.hpp`: small utilities.

Memory accounting: when compiled with `-DTHESIS_VIG_MEMORY_ACCOUNTING`, VIG builders track internal aggregation memory and expose it via `VIG::aggregation_memory` (reported by tools as `agg_memory`). Without the define, `agg_memory` is reported as `0`.

## Project structure

``` plaintext
include/thesis/       # Public headers (library API)
src/common/           # Library implementations
algorithms/           # Tool entrypoints (cnf_info, vig_info, segmentation)
benchmarks/           # Input CNFs (.cnf / .cnf.xz)
scripts/benchmarks/   # Python & bash runners, plots, registry, env
tests/                # CTest smoke tests for executables
CMakeLists.txt        # Top-level build (adds library + algorithms + tests)
```

## Building and testing

Configure and build (see Quick start). To run tests if present:

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel
ctest --test-dir build --output-on-failure
```

CI: a minimal workflow builds on Windows (`.github/workflows/ci.yml`).

macOS notes: the top-level `CMakeLists.txt` applies an SDK sysroot and system include hints via `xcrun --show-sdk-path` to ensure standard headers are found with AppleClang.

## Adding a new algorithm/tool

See `algorithms/README.md` for a short guide. In brief:

1. Create `algorithms/<your_algo>/` with a `CMakeLists.txt` and a `main.cpp`.
2. Link against `thesis::common` and use `thesis::ArgParser` for CLI.
3. Reconfigure/build to produce the new binary.
4. (Optional) Register it in `scripts/benchmarks/configs/algorithms.json` to make it available via the Python runner.

## Datasets

Sample and large inputs must be put under `benchmarks/` (can be compressed as `.xz`). The Python runner discovers `*.cnf` and `*.cnf.xz` recursively.

## Contributing

Please see [CONTRIBUTING.md](CONTRIBUTING.md).

## Citation

If you use this code in academic work, please cite the associated thesis/publication if applicable.
