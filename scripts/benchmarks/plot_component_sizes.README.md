# plot_component_sizes.py

Plot combined component-size distributions from *_components.csv files (no intermediate CSVs written).

Usage examples:

```bash
# Scan the default root and write combined plots
python3 scripts/benchmarks/plot_component_sizes.py \
  --root scripts/benchmarks/out/components \
  --outdir scripts/benchmarks/out/component_size_plots

# Process specific files only
python3 scripts/benchmarks/plot_component_sizes.py \
  --files scripts/benchmarks/out/components/segmentation/tau_100/k_500.0/94dd280b1562ee7dae44b303b8fed233-Break_unsat_18_31_components.csv \
  --outdir scripts/benchmarks/out/component_size_plots
```

Outputs (written under `--outdir`):

- `combined_topn_coverage.png`: overlay of y = percent of total nodes covered by the n largest components vs x = n (log-scaled).
- `combined_size_id_map.csv`: mapping of 3-character IDs used in legends to original labels and file paths.

Conventions & deps:

- Matches style of existing plotting scripts (seaborn + matplotlib, whitegrid).
- Requires Python with `pandas`, `numpy`, `matplotlib`, `seaborn` (see `environment.yml`).

Notes:

- Each input is assigned a unique 3-character base62-like ID (a–z, A–Z, 0–9) for concise legends.
- The mapping file includes columns: `id`, `label` (pretty label with tau/k), and `file` (path, relative to `--root` when applicable).
