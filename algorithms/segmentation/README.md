# segmentation

Segments the Variable Interaction Graph (VIG) of a CNF using a Felzenszwalb–Huttenlocher-style greedy merge.

## Usage

```bash
segmentation -i <file.cnf|-> [--tau N|inf] [--k K] [--naive|--opt] [-t K] [--maxbuf M]
```

- `-i, --input` Path to CNF or `-` for stdin
- `--tau` Clause size threshold for VIG construction (use `inf` for no limit)
- `--k` Segmentation parameter (double); higher values yield fewer merges
- `--naive` Use naive VIG builder (single-threaded)
- `--opt` Use optimized VIG builder (default)
- `-t, --threads` Threads for optimized VIG build (0 = auto)
- `--maxbuf` Max contributions buffer for optimized VIG build

Defaults: `--opt`, `--tau inf`, `--k 50.0`, `-t 0`, `--maxbuf 50000000`.

Output fields include: vars, edges, comps, k, tau, parse_sec, vig_build_sec, seg_sec, total_sec, impl, threads, agg_memory.

## Examples

```bash
segmentation -i algorithms/cnf_info/sample.cnf --tau 3 --k 50 --opt -t 2
cat algorithms/cnf_info/sample.cnf | segmentation -i - --tau inf --k 25 --naive
```
