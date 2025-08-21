# vig_info

Builds the Variable Interaction Graph (VIG) of a CNF and prints summary statistics.

## Usage

```bash
vig_info -i <file.cnf|-> [--tau N|inf] [--naive|--opt] [-t K] [--maxbuf M]
```

- `-i, --input` Path to CNF or `-` for stdin
- `--tau` Clause size threshold (use `inf` for no limit)
- `--naive` Use the naive implementation (single-threaded)
- `--opt` Use the optimized implementation (default)
- `-t, --threads` Number of worker threads (0 = auto)
- `--maxbuf` Max contributions buffer in optimized mode

Defaults: `--opt`, `--tau inf`, `-t 0`, `--maxbuf 50000000`.

Output fields include: vars, edges, parse_sec, vig_build_sec, total_sec, impl, tau, threads, agg_memory.

## Examples

```bash
vig_info -i algorithms/cnf_info/sample.cnf --tau 3 --opt -t 2
cat algorithms/cnf_info/sample.cnf | vig_info -i - --tau inf --naive
```
