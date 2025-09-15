# segmentation_eval

Run segmentation sweeps efficiently by parsing the CNF once, building two VIGs once (tau=inf and tau=user), and then:

- Running segmentation on the user-tau VIG for one or more k values without rebuilding the VIG
- Reusing the resulting labels on the tau=inf VIG to compute modularity Q
- Printing one summary line per segmentation run (easy to collect into CSV)

This binary is meant to streamline benchmarking by avoiding repeated parsing and VIG construction work across multiple segmentation settings. All results are written to a CSV file; stdout is used only for status updates and failure reporting.

## Usage

```bash
segmentation_eval -i <file.cnf|-> --out-csv <file.csv> [--tau N|inf] [--naive|--opt] [-t N] [--maxbuf M]
                  -k K[,K2,...]
                  [--norms on|off[,..]] [--norm-sample N | --norm-samples N[,..]]
                  [--size-exp X[,..]]
                  [--mod-guard on|off[,..]] [--gamma G[,..]]
                  [--anneal on|off[,..]] [--dq-tol0 T[,..]] [--dq-vscale S[,..]]
                  [--ambiguous accept|reject|margin[,..]] [--gate-margin R[,..]]
```

- -i, --input FILE|-  Path to DIMACS CNF file, or '-' to read from stdin
- --out-csv FILE      Required path to the output CSV file (results written here)
- --tau N|inf         Clause size threshold for the “user VIG” used by segmentation (use 'inf' for no limit)
- -k K[,K2,...]       One or more segmentation k parameters (comma-separated doubles). Default: 50.0
- --naive             Use naive VIG builder (single-threaded)
- --opt               Use optimized VIG builder (default)
- -t, --threads N     Threads for optimized VIG (0 = auto; default 0)
- --maxbuf M          Max contributions buffer for optimized VIG (default 50,000,000)
- Sweeping knobs:
  - --norms on|off[,..]     List of normalization on/off values (fallback to --no-norm if not provided)
  - --norm-sample N         Single value for top-edges sample size used for normalization (default 1000)
  - --norm-samples N[,..]   List of sample sizes
  - --size-exp X[,..]       Size exponent(s) (default 1.95). 1.0 ≈ k/|C|
  - --mod-guard on|off[,..] List of modularity-guard on/off values (fallback to --no-mod-guard)
  - --gamma G[,..]          Modularity resolution(s) for the guard (default 1.0)
  - --anneal on|off[,..]    List of annealing on/off (fallback to --no-anneal-guard)
  - --dq-tol0 T[,..]        Initial ΔQ tolerance values (default 5e-4)
  - --dq-vscale S[,..]      ΔQ anneal scale values (0 => auto; default 0)
  - --ambiguous POLICY[,..] Ambiguous policy values: accept|reject|margin (default margin)
  - --gate-margin R[,..]    Gate margin ratio values for margin policy (default 0.05)

Notes:

- The tool always builds two VIGs exactly once each: one with tau=inf (for modularity evaluation) and one with the user-provided tau (for segmentation).
- For multiple k values, the VIGs are reused; only the segmentation step repeats.

## Output

For each configuration (cartesian product of provided lists), the tool appends one row to the output CSV with the following columns:

- vars                Number of variables (nodes)
- edges_user          Edges in the user-tau VIG
- edges_inf           Edges in the tau=inf VIG
- comps               Number of components produced by segmentation
- k                   Segmentation parameter used
- tau_user            The user tau (−1 denotes inf)
- seg_sec             Seconds spent in segmentation for this k
- total_sec           Total seconds since program start (parse + both VIG builds + current seg)
- impl                VIG builder used: naive or opt
- threads             Number of threads (−1 denotes auto when using opt)
- agg_memory_inf      Aggregation buffer footprint for tau=inf build (bytes)
- agg_memory_user     Aggregation buffer footprint for user-tau build (bytes)
- keff, gini, pmax, entropyJ  Component size distribution metrics
- modularity Modularity Q of the segmentation labels evaluated on the tau=inf VIG (gamma=1)
- normalize, norm_sample, size_exp, modGuard, gamma, anneal, dqTol0, dqVscale, amb, gateMargin
- modGateAcc, modGateRej, modGateAmb (guard counters)

Stdout behavior:

- Prints a startup line with the total number of rows and the CSV path.
- Prints periodic progress lines (every ~1000 rows).
- Prints a final completion line with the row count and CSV path.
- Errors are reported to stderr and a nonzero exit code is returned.

These lines are CSV-friendly; you can collect them into a file and parse by splitting on spaces and '='.

## Examples

- Single k, default optimized builder with auto threads:

```bash
segmentation_eval -i path/to/formula.cnf --tau 10 -k 50 --out-csv /tmp/seg_sweep.csv
```

- Multiple k values without rebuilding VIG:

```bash
segmentation_eval -i path/to/formula.cnf --tau 5 -k 10,30,100 --out-csv /tmp/seg_sweep.csv
```

- Streaming a compressed CNF (.xz) via stdin:

```bash
xz -dc path/to/formula.cnf.xz | segmentation_eval -i - --tau inf -k 25,50,75 --out-csv /tmp/seg_sweep.csv
```

- Sweeping multiple knobs at once (small demo):

```bash
segmentation_eval -i path/to/formula.cnf --tau 10 -k 10,30 \
  --norms on,off --norm-samples 100,1000 --size-exp 1.0,1.95 \
    --mod-guard on,off --gamma 1.0,0.5 --anneal on,off \
    --dq-tol0 5e-4,1e-3 --dq-vscale 0,10 \
  --ambiguous accept,reject,margin --gate-margin 0.01,0.05 \
  --out-csv /tmp/seg_sweep.csv
```

- Using the naive single-threaded builder (for comparison/baselines):

```bash
segmentation_eval -i path/to/formula.cnf --tau 8 -k 50 --naive --out-csv /tmp/seg_sweep.csv
```

## Performance tips

- Prefer the optimized builder (`--opt`, default) with `-t 0` (auto threads). Increase `--maxbuf` if you have ample memory and see many batches during VIG construction.
- Sweep many k values in a single invocation to avoid repeated parsing and VIG builds.
- If you benchmark across different tau values, call the tool once per tau (each run still builds only two VIGs once).

## Rationale

- tau=inf VIG often serves as the most inclusive graph for modularity evaluation. Segmenting on a stricter user tau and evaluating modularity on tau=inf enables consistent cross-tau comparisons while retaining segmentation speed.

## Exit codes

- 0: success
- 1: CLI error or invalid k specification
- 2: CNF parse failure
- 3: (reserved for future output/file errors)

## See also

- `algorithms/segmentation` — segmentation on a single VIG
- `algorithms/vig_info` — VIG statistics and optional graph dumps
- `algorithms/louvain` — Louvain community detection and modularity
