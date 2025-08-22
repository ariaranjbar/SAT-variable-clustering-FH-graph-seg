# Benchmark scripts for algorithms

This folder contains helper scripts to run algorithms on random subsets of the benchmarks in `../../benchmarks` and collect metrics.

You can use either the Python runner (recommended) or the legacy bash helpers:

- Python dynamic runner: `scripts/benchmarks/bench_runner.py <algo> ...` with algorithms defined once in `configs/algorithms.json` (auto-discovered as CLI subcommands).
- Bash helpers (legacy):
  - `run_vig_info_random.sh` — runs `vig_info` on N random CNFs; writes `out/vig_info_results.csv`.
  - `run_segmentation_random.sh` — runs `segmentation` on N random CNFs; writes `out/segmentation_results.csv`.

Quick start:

```bash
# After building the project, e.g., cmake -S . -B build && cmake --build build -j

# Python runner (registry-driven): runs vig_info with sweeps; --bin optional (auto-discovery)
python3 scripts/benchmarks/bench_runner.py vig_info -n 5 \
  --implementations naive,opt --taus 3,5,10,inf --threads 1,2,4 --maxbufs 50000000,100000000 \
  --skip-existing -v

# Segmentation via Python runner
python3 scripts/benchmarks/bench_runner.py segmentation -n 5 \
  --implementations naive,opt --taus 3,5,10,inf --ks 25,50,100 --threads 1,2,4 --maxbufs 50000000,100000000 \
  --skip-existing -v

# Legacy bash (optional)
scripts/benchmarks/run_vig_info_random.sh -n 5 --bin build/algorithms/vig_info/vig_info \
  --taus 3,5,10,inf --threads 1,2,4 --maxbufs 50000000,100000000 --implementations opt
scripts/benchmarks/run_segmentation_random.sh -n 5 --bin build/algorithms/segmentation/segmentation \
  --taus 3,5,10,inf --ks 25,50,100 --threads 1,2,4 --maxbufs 50000000,100000000
```

Notes:

- Python runner auto-discovers binaries based on the registry; `--bin` can override.
- `--implementations naive,opt` lets you restrict runs; using only `opt` is typical when sweeping threads/maxbuf.
- Requires `xz` for streaming decompression of `.xz` inputs.
- CSV columns:
  - VIG: `file,impl,tau,threads,maxbuf,memlimit_mb,vars,edges,total_sec,parse_sec,vig_build_sec,agg_memory`.
    - total_sec is the end-to-end runtime of vig_info
    - parse_sec and vig_build_sec are optional component timings when the tool reports them
  - Segmentation: `file,impl,tau,k,threads,maxbuf,memlimit_mb,vars,edges,comps,keff,gini,pmax,entropyJ,total_sec,parse_sec,vig_build_sec,seg_sec,agg_memory`.
    - keff, gini, pmax, entropyJ come from `thesis/comp_metrics.hpp` and summarize component balance
    - seg_sec is the segmentation phase time; others as above
- Logs are cleaned up on successful runs and kept only on failures or when no summary could be parsed.

Implementation notes:

- Common helpers live in `lib_bench.sh` and are sourced by both scripts to avoid duplication (verbose logging and portable shuffling).

Tau semantics:

- `tau` is the maximum clause size included. Clauses with size > tau are discarded.
- Use `tau >= 3` or `inf`. The runner enforces constraints via the registry schema.

## Config-driven mode

You can run fully configurable sweeps via a JSON/YAML file (minimal config using registry schema):

```bash
scripts/benchmarks/bench_runner.py config --file scripts/benchmarks/configs/example_configs.json -v
```

The config uses the registry’s command, CSV schema, and parameter definitions by default; you only override values you want to sweep. It supports conditions (from the registry), memlimit sweeps, skip-existing, and file reuse. See `scripts/benchmarks/configs/README.md` for details.

### Dynamic algorithm registry (define once, reuse via CLI)

- Define algorithms in `scripts/benchmarks/configs/algorithms.json` to register them as subcommands.
- The registry holds binary discovery, command templates, parameter schemas (with validation), and CSV shapes.
- Example:

```bash
python3 scripts/benchmarks/bench_runner.py vig_info -n 5 \
  --implementations naive,opt --taus 3,5,10,inf --threads 1,2,4 --maxbufs 50000000,100000000 \
  --skip-existing --dry-run -v
```

This lets you add or update algorithms without changing Python code.
