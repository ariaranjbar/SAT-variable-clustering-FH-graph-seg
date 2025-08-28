# louvain

Computes Louvain community structure on the Variable Interaction Graph (VIG) of a CNF.

## Usage

```bash
louvain -i <file.cnf|-> [--tau N|inf] [--nb-pass K] [--min-mod EPS] [--graph-out BASE]
```

- `-i, --input` Path to DIMACS CNF or `-` for stdin
- `--tau` Clause size threshold for building the VIG (use `inf` for no limit)
- `--nb-pass` Maximum passes per Louvain level (`-1` = until convergence)
- `--min-mod` Minimum modularity improvement per pass (epsilon)
- `--graph-out BASE` Write the final community assignment and graph to `BASE.node.csv` and `BASE.edges.csv`

Defaults: `--tau inf`, `--nb-pass -1`, `--min-mod 1e-7`.

## Output

Prints a single summary line with key=value pairs:

- `vars` Number of CNF variables
- `parse_sec` Seconds spent parsing the CNF
- `louvain_graph_sec` Seconds to build the Louvain/VIG graph (given `tau`)
- `louvain_sec` Seconds spent in the Louvain optimization
- `total_sec` Total runtime in seconds
- `tau` Clause size threshold used (`-1` denotes `inf`)
- `mod0` Initial modularity
- `mod1` Modularity after the first level optimization
- `comps` Number of communities detected
- `improved` `1` if modularity improved at the first level, else `0`

When `--graph-out BASE` is provided, two CSV files are written:

- `BASE.node.csv` Columns: `id,component` (node id and its community id)
- `BASE.edges.csv` Columns: `u,v,w` (undirected edges with weight, emitted once for `u < v`)

## Examples

```bash
# Basic run on a sample CNF
louvain -i algorithms/cnf_info/sample.cnf --tau 3

# Stream from stdin, run until convergence with default epsilon
cat algorithms/cnf_info/sample.cnf | louvain -i - --tau inf --nb-pass -1 --min-mod 1e-7

# Also write community labels and the (undirected) graph CSVs
louvain -i algorithms/cnf_info/sample.cnf --tau 5 --graph-out /tmp/sample_louvain
```

## Benchmark runners

To integrate this tool with the Python benchmark runner, follow the guidance in `algorithms/README.md` and add an entry to `scripts/benchmarks/configs/algorithms.json` (discover rule, command template, params, and required output keys).
