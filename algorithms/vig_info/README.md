# vig_info

Builds the Variable Interaction Graph (VIG) of a CNF and prints summary statistics.

## Usage

```bash
vig_info -i <file.cnf|-> [--tau N|inf] [--naive|--opt] [-t K] [--maxbuf M] [--graph-out FILE]
```

- `-i, --input` Path to CNF or `-` for stdin
- `--tau` Clause size threshold (use `inf` for no limit)
- `--naive` Use the naive implementation (single-threaded)
- `--opt` Use the optimized implementation (default)
- `-t, --threads` Number of worker threads (0 = auto)
- `--maxbuf` Max contributions buffer in optimized mode
- `--graph-out FILE` Write the graph to `FILE.node.csv` and `FILE.edges.csv`

Defaults: `--opt`, `--tau inf`, `-t 0`, `--maxbuf 50000000`.

Output fields include: `vars, edges, parse_sec, vig_build_sec, total_sec, impl, tau, threads, agg_memory`.

## Examples

```bash
vig_info -i algorithms/cnf_info/sample.cnf --tau 3 --opt -t 2
cat algorithms/cnf_info/sample.cnf | vig_info -i - --tau inf --naive
vig_info -i algorithms/cnf_info/sample.cnf --tau inf --opt --graph-out /tmp/sample_vig
```

## Benchmark runners

You can sweep many files and configurations using the benchmark runners in `scripts/benchmarks/`.

- Python (recommended):

```bash
python scripts/benchmarks/bench_runner.py vig_info -n 5 \
  --implementations naive,opt --taus 3,5,10,inf --threads 1,2,4 --maxbufs 50000000,100000000 \
  --skip-existing -v
```

- Bash (legacy): `scripts/benchmarks/run_vig_info_random.sh -n 5`.
