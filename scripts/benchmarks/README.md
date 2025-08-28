# Benchmark scripts for algorithms

Tools in this folder help you run and visualize experiments over the CNF benchmarks in `../../benchmarks` and collect CSV outputs.

Contents overview:

- `bench_runner.py` — registry-driven runner for batch experiments (recommended)
- `plot.sh` — convenience wrapper to set up a Conda env and generate plots/visualizations
- `plot_vig_info_results.py` — make plots from `vig_info_results.csv`
- `plot_segmentation_results.py` — make plots from `segmentation_results.csv`
- `visualize_graph.py` — render `.node.csv`/`.edges.csv` graph files to an image
- `generate_and_visualize_graph.py` — generate graph CSVs via binaries and auto-render images
- `configs/` — algorithms registry and config examples
- `environment.yml` — optional Python environment for plotting and visualization
- `lib_bench.sh` — tiny bash helpers (verbose logging, portable shuffling)

## 1) Batch runner (recommended)

Runs algorithms defined in `configs/algorithms.json` as first-class CLI subcommands. Handles binary discovery, parameter sweeps, input selection, CSV writing, and log management.

```bash
# Examples (after building binaries under build/)
python scripts/benchmarks/bench_runner.py vig_info -n 5 \
  --implementations naive,opt --taus 3,5,10,inf --threads 1,2,4 --maxbufs 50000000,100000000 \
  --skip-existing -v

python scripts/benchmarks/bench_runner.py segmentation -n 5 \
  --implementations opt --taus 3,5,10,inf --ks 25,50,100 --threads 1,2,4 \
  --skip-existing -v
```

Notes:

- Binaries are auto-discovered from `configs/algorithms.json` (`build/...` paths) or by name; use `--bin` to override.
- `.xz` inputs are streamed via `xz -dc` when present; otherwise files are read directly.
- CSV shapes and required keys are declared per algorithm in the registry (see `configs/algorithms.json`).
- Config mode allows multiple algorithms and richer overrides:

```bash
python scripts/benchmarks/bench_runner.py config --file scripts/benchmarks/configs/example_configs.json -v
```

Tau semantics: `tau` caps clause size; clauses larger than `tau` are ignored. Use integer ≥ 2 or `inf`.

## 2) Plotting and visualization

### plot.sh (wrapper)

Creates/updates a Conda env (`thesis-bench`), installs Python deps as needed, then runs:

- VIG plots to `scripts/benchmarks/out/vig_info_plots`
- Segmentation plots to `scripts/benchmarks/out/segmentation_plots`
- Graph image renders for any `out/graphs/*(node|nodes).csv` + `*.edges.csv` pairs

Usage:

```bash
scripts/benchmarks/plot.sh        # create env if needed and plot
scripts/benchmarks/plot.sh --update  # update env from environment.yml before plotting
```

### plot_vig_info_results.py

Generate heatmaps/lines from `vig_info_results.csv` (columns as declared in the registry).

```bash
python scripts/benchmarks/plot_vig_info_results.py \
  --csv scripts/benchmarks/out/vig_info_results.csv \
  --outdir scripts/benchmarks/out/vig_info_plots \
  --impl opt   # optional filter
```

### plot_segmentation_results.py

Generate heatmaps over `tau × k` and optional balance metrics.

```bash
python scripts/benchmarks/plot_segmentation_results.py \
  --csv scripts/benchmarks/out/segmentation_results.csv \
  --outdir scripts/benchmarks/out/segmentation_plots
```

### visualize_graph.py

Render graph CSVs to an image. Accepts `--nodes` (`id[,component]`) and `--edges` (`u,v,w`).

```bash
python scripts/benchmarks/visualize_graph.py \
  --nodes scripts/benchmarks/out/graphs/graph_output.seg.node.csv \
  --edges scripts/benchmarks/out/graphs/graph_output.seg.edges.csv \
  --out   scripts/benchmarks/out/graphs/graph_output.seg.png \
  --title "Segmentation"
```

### generate_and_visualize_graph.py

Use the built binaries to produce `.node.csv`/`.edges.csv` for both segmentation and VIG, then render PNGs.

```bash
python scripts/benchmarks/generate_and_visualize_graph.py benchmarks/your.cnf.xz
```

Outputs are written to `scripts/benchmarks/out/graphs/graph_output.{seg|vig}.*`.

## 3) Environment

Optional Conda environment for plotting and visualization:

```bash
conda env create -f scripts/benchmarks/environment.yml
conda activate thesis-bench
```

## 4) CSV columns (reference)

- VIG results: `file,impl,tau,threads,maxbuf,memlimit_mb,vars,edges,total_sec,parse_sec,vig_build_sec,agg_memory`.
- Segmentation results: `file,impl,tau,k,threads,maxbuf,size_exp,norm_sample,normalize,modGuard,gamma,anneal,dqTol0,dqVscale,amb,gateMargin,modGateAcc,modGateRej,modGateAmb,memlimit_mb,vars,edges,comps,modularity,keff,gini,pmax,entropyJ,total_sec,parse_sec,vig_build_sec,seg_sec,agg_memory`.

Logs are cleaned up on success and kept only on failures or when no summary could be parsed.
