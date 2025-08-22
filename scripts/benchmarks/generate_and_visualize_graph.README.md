# generate_and_visualize_graph.py

Generate graph CSVs using the C++ binaries, then render PNG images.

It runs:

- `segmentation` with `--graph-out` to produce `*.node.csv` and `*.edges.csv` with component labels
- `vig_info` with `--graph-out` to produce VIG `*.node.csv` and `*.edges.csv`
- `visualize_graph.py` to render PNGs for each

Usage:

```bash
python3 scripts/benchmarks/generate_and_visualize_graph.py path/to/input.cnf.xz
```

Details:

- Auto-detects `.xz` inputs and streams via `xz -dc`.
- Writes outputs under `scripts/benchmarks/out/graphs/` with fixed basenames:
  - `graph_output.seg.(node|edges).csv` and `graph_output.seg.png`
  - `graph_output.vig.(node|edges).csv` and `graph_output.vig.png`
- Requires built binaries at:
  - `build/algorithms/segmentation/segmentation`
  - `build/algorithms/vig_info/vig_info`

Options:

- `--layout`, `--max-nodes`, `--max-edges` are forwarded to `visualize_graph.py`.

Exit codes:

- 2: missing input/binary/script
- 3: expected CSV not produced by the binaries
