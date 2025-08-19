# Benchmark scripts for algorithms

This folder contains helper scripts to run algorithms on random subsets of the benchmarks in `../../benchmarks` and collect metrics.

Currently available:

- `run_vig_info_random.sh`: runs the `vig_info` executable (from `algorithms/vig_info`) on N random CNF benchmarks. It supports `.cnf` and `.cnf.xz` files, streaming decompression for the latter. Results are appended to `out/results.csv` and per-run logs are saved in `out/`.

Quick start:

```bash
# After building the project, e.g., cmake -S . -B build && cmake --build build -j
scripts/benchmarks/run_vig_info_random.sh -n 5 --bin build/algorithms/vig_info/vig_info \
  --taus 3,5,10,inf --threads 1,2,4 --maxbufs 50000000,100000000
```

Notes:

- If `--bin` is omitted, the script will try a few common binary locations under `build/`.
- Requires `xz` for streaming decompression.
- CSV columns: `file,impl,tau,threads,maxbuf,memlimit_mb,vars,edges,time_sec,agg_memory`.

Tau semantics:

- `tau` is the maximum clause size included. Clauses with size > tau are discarded.
- Use `tau >= 3` or `inf`. The script filters out tau <= 2.
