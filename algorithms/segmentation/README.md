# segmentation

Segment the Variable Interaction Graph (VIG) of a CNF using a Felzenszwalb–Huttenlocher-style greedy merge with optional distance normalization and a modularity guard.

## Usage

```bash
segmentation -i <file.cnf|-> [--tau N|inf] [--k K] [--naive|--opt] [-t N] [--maxbuf M]
             [--graph-out DIR] [--comp-out DIR] [--cross-out DIR] [--output-base NAME]
             [--no-norm] [--norm-sample N] [--size-exp X]
             [--no-mod-guard] [--gamma G] [--no-anneal-guard] [--dq-tol0 T] [--dq-vscale S]
             [--ambiguous {accept|reject|margin}] [--gate-margin R]
```

Required/primary options:

- -i, --input FILE|-  Path to DIMACS CNF, or '-' to read from stdin
- --tau N|inf         Clause size threshold for VIG construction (use 'inf' for no limit)
- -k, --k K           Segmentation parameter (double); higher → fewer merges
- --naive             Use the naive VIG builder (single-threaded)
- --opt               Use the optimized VIG builder (default)
- -t, --threads N     Threads for optimized VIG build (0 = auto)
- --maxbuf M          Max contributions buffer for optimized VIG build

Outputs (optional files):

- --graph-out DIR     Write graph CSVs into DIR as `<base>.node.csv` and `<base>.edges.csv`
  - Nodes CSV: columns `id,component`
  - Edges CSV: columns `u,v,w` (undirected, once for u<v)
- --comp-out DIR      Write component summary to `DIR/<base>_components.csv` (sorted by size desc)
- --cross-out DIR     Write strongest cross-component edges to `DIR/<base>_cross.csv` (sorted by weight desc)
- --output-base NAME  Override `<base>` used for all outputs; defaults to input basename or `stdin`
- --comp-base NAME    [deprecated] Old base name flag; prefer `--output-base`

Segmentation behavior knobs:

- --no-norm           Disable distance normalization (default: enabled)
- --norm-sample N     Top edges sampled for normalization median (default: 1000)
- --size-exp X        Size exponent in gate denominator (default: 1.2). 1.0 ≈ k/|C|

Modularity guard knobs (for ΔQ gating during merges):

- --no-mod-guard      Disable modularity guard (default: enabled)
- --gamma G           Modularity resolution used by the guard (default: 1.0)
- --no-anneal-guard   Disable annealing of ΔQ tolerance (default: annealing on)
- --dq-tol0 T         Initial ΔQ tolerance (default: 5e-4)
- --dq-vscale S       Scale for tolerance annealing; 0 => auto (~mean degree) (default: 0)
- --ambiguous POLICY  Ambiguous policy: `accept`, `reject`, or `margin` (default: `margin`)
- --gate-margin R     Gate margin ratio for `margin` policy (default: 0.05)

Defaults: `--opt`, `--tau inf`, `--k 50.0`, `-t 0`, `--maxbuf 50000000`, normalization on with `--norm-sample 1000`, `--size-exp 1.2`, modularity guard on with `--gamma 1.0`, annealing on, `--dq-tol0 5e-4`, `--dq-vscale 0`, ambiguous=`margin`, `--gate-margin 0.05`.

## Output (stdout)

Prints a single summary line (key=value pairs) for the run:

```text
vars, edges, comps, k, tau, parse_sec, vig_build_sec, seg_sec, total_sec,
impl, threads, agg_memory,
keff, gini, pmax, entropyJ,
modularity,
normalize, norm_sample, size_exp,
modGuard, gamma, anneal, dqTol0, dqVscale,
amb, gateMargin,
modGateAcc, modGateRej, modGateAmb
```

Notes:

- `tau` uses `-1` to denote `inf`.
- `modularity` is computed on the built VIG (with the given `tau`) using resolution gamma fixed to 1.0 for reporting (independent of the guard’s `--gamma`).
- `modGate*` counters report decisions taken by the modularity guard during segmentation.

## Examples

```bash
segmentation -i algorithms/cnf_info/sample.cnf --tau 3 --k 50 --opt -t 2
```

```bash
cat algorithms/cnf_info/sample.cnf | segmentation -i - --tau inf --k 25 --naive
```

```bash
segmentation -i algorithms/cnf_info/sample.cnf --tau inf --k 50 --opt \
  --graph-out /tmp/out --comp-out /tmp/out --cross-out /tmp/out --output-base sample
```

## Benchmark runners

Sweep files and configurations using the benchmark runners in `scripts/benchmarks/`.

- Python (recommended):

```bash
python scripts/benchmarks/bench_runner.py segmentation -n 5 \
  --implementations naive,opt --taus 3,5,10,inf --ks 25,50,100 --threads 1,2,4 --maxbufs 50000000,100000000 \
  --skip-existing -v
```

- Bash (legacy):

```bash
scripts/benchmarks/run_segmentation_random.sh -n 5
```
