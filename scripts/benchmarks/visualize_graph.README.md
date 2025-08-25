# visualize_graph.py

Visualize graph CSVs produced by the C++ tools when using `--graph-out`.

Inputs:

- Nodes CSV: `id` column required; optional `component` column to color nodes by component (from `segmentation`).
- Edges CSV: `u,v,w` columns (weight `w` used to scale edge width).

Basic usage:

```bash
python3 scripts/benchmarks/visualize_graph.py \
  --nodes scripts/benchmarks/out/graphs/graph_output.seg.node.csv \
  --edges scripts/benchmarks/out/graphs/graph_output.seg.edges.csv \
  --out   scripts/benchmarks/out/graphs/graph_output.seg.png \
  --title "Segmentation"
```

Options:

- `--layout {spring,kamada,spectral,planar,random}` — layout algorithm (default: `spring`)
- `--max-nodes N`, `--max-edges M` — subsample for large graphs (0 = no cap)
- `--node-size`, `--edge-alpha`, `--edge-min-width`, `--edge-max-width`, `--weight-scale` — visual tuning
- `--no-legend`, `--no-labels` — disable legend or labels
- `--edge-labels` — draw edge weights as labels (can clutter large graphs)
- `--edge-labels-max N` — label at most N strongest edges (default: 200)
- `--edge-labels-fmt F` — Python format spec for weights (default: `.3g`, e.g., `.2f`)

Dependencies:

- Python packages: `matplotlib`, `networkx` (install via Conda env `thesis-bench` or pip)

Output:

- Image written to the `--out` path. Prints a short summary on stdout.
