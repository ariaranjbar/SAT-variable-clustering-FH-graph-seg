# Benchmark scripts for algorithms

This folder contains helper scripts to run algorithms on random subsets of the benchmarks in `../../benchmarks` and collect metrics.

Currently available:

- `run_vig_info_random.sh`: runs the `vig_info` executable (from `algorithms/vig_info`) on N random CNF benchmarks. It supports `.cnf` and `.cnf.xz` files, streaming decompression for the latter. Results are appended to `out/vig_info_results.csv` and per-run logs are saved in `out/`.
- `run_segmentation_random.sh`: runs the `segmentation` executable (from `algorithms/segmentation`) on N random CNF benchmarks. It supports `.cnf` and `.cnf.xz` files and sweeps tau, k, threads, and maxbuf. Results are appended to `out/segmentation_results.csv`.

Quick start:

```bash
# After building the project, e.g., cmake -S . -B build && cmake --build build -j
scripts/benchmarks/run_vig_info_random.sh -n 5 --bin build/algorithms/vig_info/vig_info \
  --taus 3,5,10,inf --threads 1,2,4 --maxbufs 50000000,100000000

# Segmentation example
scripts/benchmarks/run_segmentation_random.sh -n 5 --bin build/algorithms/segmentation/segmentation \
  --taus 3,5,10,inf --ks 25,50,100 --threads 1,2,4 --maxbufs 50000000,100000000
```

Notes:

- If `--bin` is omitted, the script will try a few common binary locations under `build/`.
- Requires `xz` for streaming decompression.
- CSV columns:
  - VIG: `file,impl,tau,threads,maxbuf,memlimit_mb,vars,edges,total_sec,parse_sec,vig_build_sec,agg_memory`.
    - total_sec is the end-to-end runtime of vig_info
    - parse_sec and vig_build_sec are optional component timings when the tool reports them
  - Segmentation: `file,impl,tau,k,threads,maxbuf,memlimit_mb,vars,edges,comps,total_sec,parse_sec,vig_build_sec,seg_sec,agg_memory`.
    - seg_sec is the segmentation phase time; others as above
- Logs are cleaned up on successful runs and kept only on failures or when no summary could be parsed.

Implementation notes:

- Common helpers live in `lib_bench.sh` and are sourced by both scripts to avoid duplication (verbose logging and portable shuffling).

Tau semantics:

- `tau` is the maximum clause size included. Clauses with size > tau are discarded.
- Use `tau >= 3` or `inf`. The script filters out tau <= 2.
