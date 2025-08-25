#!/usr/bin/env python3
"""
Visualize graph CSVs produced by --graph-out (nodes and edges files).

Inputs:
  - nodes CSV: must have column 'id'; may optionally have 'component' for coloring (from segmentation).
  - edges CSV: must have columns 'u','v','w' (weight is used to scale edge width).

Example:
  python3 scripts/visualize_graph.py \
    --nodes scripts/benchmarks/out/graphs/graph_output.seg.node.csv \
    --edges scripts/benchmarks/out/graphs/graph_output.seg.edges.csv \
    --out   scripts/benchmarks/out/graphs/graph_output.seg.png \
    --title "graph_output segmentation"

If you only have VIG CSVs (no component column), nodes will be a single color.

Dependencies (recommended via conda env 'thesis-bench'):
  - matplotlib
  - networkx

Install (optional):
  python3 -m pip install --user matplotlib networkx
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import random
import sys
from typing import List, Optional, Tuple

# Prefer a non-interactive backend for headless environments before importing pyplot
try:
    import matplotlib as mpl
    # If no backend is set, prefer Agg (safe for file output)
    if not mpl.get_backend() or mpl.get_backend().lower() in {"macosx", "tkagg", "qt5agg"}:
        try:
            mpl.use("Agg")
        except Exception:
            pass
    import matplotlib.pyplot as plt
    import networkx as nx
except Exception as e:
    sys.stderr.write(
        "Missing dependencies. Please install with:\n  python3 -m pip install --user matplotlib networkx\n\nError: %s\n"
        % e
    )
    sys.exit(1)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Visualize graph from nodes/edges CSVs.")
    p.add_argument("--nodes", required=True, help="Path to nodes CSV (id[,component])")
    p.add_argument("--edges", required=True, help="Path to edges CSV (u,v,w)")
    p.add_argument("--out", required=True, help="Output image path (e.g., .png, .pdf)")
    p.add_argument("--title", default=None, help="Figure title")
    p.add_argument("--layout", default="spring", choices=[
        "spring", "kamada", "spectral", "planar", "random"
    ], help="Layout algorithm")
    p.add_argument("--max-nodes", type=int, default=2000, help="Max nodes to draw (randomly subsampled if exceeded; 0=all)")
    p.add_argument("--max-edges", type=int, default=8000, help="Max edges to draw (randomly subsampled if exceeded; 0=all)")
    p.add_argument("--seed", type=int, default=42, help="Random seed for sampling/layout")
    p.add_argument("--dpi", type=int, default=200, help="Figure DPI")
    p.add_argument("--width", type=float, default=10.0, help="Figure width in inches")
    p.add_argument("--height", type=float, default=8.0, help="Figure height in inches")
    p.add_argument("--node-size", type=float, default=12.0, help="Node size for drawing")
    p.add_argument("--edge-alpha", type=float, default=0.25, help="Edge alpha (transparency)")
    p.add_argument("--edge-min-width", type=float, default=0.25, help="Minimum edge width")
    p.add_argument("--edge-max-width", type=float, default=2.5, help="Maximum edge width")
    p.add_argument("--weight-scale", type=float, default=1.0, help="Multiply sqrt(weight) by this when computing width")
    p.add_argument("--no-legend", action="store_true", help="Disable legend even if components present")
    p.add_argument("--no-labels", action="store_true", help="Do not draw node labels")
    # Edge weight labels (optional, can clutter on large graphs)
    p.add_argument("--edge-labels", action="store_true", help="Draw edge weight labels for up to --edge-labels-max strongest edges")
    p.add_argument("--edge-labels-max", type=int, default=200, help="Max number of edges to label (strongest by weight)")
    p.add_argument("--edge-labels-fmt", type=str, default=".3g", help="Python format spec for weights (e.g., .2f, .3g)")
    return p.parse_args()


def read_nodes(nodes_path: str) -> Tuple[List[int], Optional[List[int]]]:
    node_ids: List[int] = []
    components: Optional[List[int]] = None
    with open(nodes_path, newline="") as f:
        rdr = csv.DictReader(f)
        if "id" not in rdr.fieldnames:
            raise ValueError(f"nodes CSV missing 'id' column: {rdr.fieldnames}")
        has_comp = "component" in rdr.fieldnames
        if has_comp:
            components = []
        for row in rdr:
            try:
                vid = int(row["id"]) if row["id"] != "" else None
            except Exception:
                continue
            if vid is None:
                continue
            node_ids.append(vid)
            if has_comp and components is not None:
                try:
                    components.append(int(row["component"]))
                except Exception:
                    components.append(-1)
    return node_ids, components


def read_edges(edges_path: str) -> List[Tuple[int, int, float]]:
    edges: List[Tuple[int, int, float]] = []
    with open(edges_path, newline="") as f:
        rdr = csv.DictReader(f)
        need = {"u", "v", "w"}
        if not need.issubset(set(rdr.fieldnames or [])):
            raise ValueError(f"edges CSV missing columns; expected {need}, got {rdr.fieldnames}")
        for row in rdr:
            try:
                u = int(row["u"]) if row["u"] != "" else None
                v = int(row["v"]) if row["v"] != "" else None
                w = float(row["w"]) if row["w"] != "" else 1.0
            except Exception:
                continue
            if u is None or v is None:
                continue
            edges.append((u, v, w))
    return edges


def sample_graph(
    node_ids: List[int],
    components: Optional[List[int]],
    edges: List[Tuple[int, int, float]],
    max_nodes: int,
    max_edges: int,
    seed: int,
) -> Tuple[List[int], Optional[List[int]], List[Tuple[int, int, float]]]:
    random.seed(seed)

    # Node sampling
    if max_nodes and len(node_ids) > max_nodes:
        idxs = list(range(len(node_ids)))
        keep_idx = set(random.sample(idxs, max_nodes))
        sampled_nodes = [node_ids[i] for i in sorted(keep_idx)]
        sampled_comp = [components[i] for i in sorted(keep_idx)] if components is not None else None
        keep_set = set(sampled_nodes)
    else:
        sampled_nodes = node_ids
        sampled_comp = components
        keep_set = set(node_ids)

    # Edge filtering to nodes
    filtered_edges = [(u, v, w) for (u, v, w) in edges if (u in keep_set and v in keep_set)]

    # Edge sampling
    if max_edges and len(filtered_edges) > max_edges:
        filtered_edges = random.sample(filtered_edges, max_edges)

    return sampled_nodes, sampled_comp, filtered_edges


def compute_layout(G: "nx.Graph", layout: str, seed: int):
    if layout == "spring":
        return nx.spring_layout(G, seed=seed)
    if layout == "kamada":
        return nx.kamada_kawai_layout(G)
    if layout == "spectral":
        return nx.spectral_layout(G)
    if layout == "planar":
        try:
            return nx.planar_layout(G)
        except Exception:
            return nx.spring_layout(G, seed=seed)
    if layout == "random":
        return nx.random_layout(G)
    return nx.spring_layout(G, seed=seed)


def build_graph(node_ids: List[int], components: Optional[List[int]], edges: List[Tuple[int, int, float]]):
    G = nx.Graph()
    if components is None:
        for vid in node_ids:
            G.add_node(vid)
    else:
        for vid, comp in zip(node_ids, components):
            G.add_node(vid, component=comp)
    for u, v, w in edges:
        G.add_edge(u, v, weight=w)
    return G


def make_colors(node_ids: List[int], components: Optional[List[int]]):
    if components is None:
        return ["#1f77b4" for _ in node_ids], None
    comps = components
    uniq = sorted(set(comps))
    try:
        cmap = mpl.colormaps.get_cmap("tab20")
    except Exception:
        cmap = mpl.cm.get_cmap("tab20")
    comp_to_idx = {c: i for i, c in enumerate(uniq)}
    colors = [mpl.colors.to_hex(cmap(comp_to_idx[c] % getattr(cmap, 'N', 20))) for c in comps]
    # Legend handles
    handles = None
    if len(uniq) <= 20:
        handles = []
        for c in uniq:
            color = mpl.colors.to_hex(cmap(comp_to_idx[c] % getattr(cmap, 'N', 20)))
            handles.append(mpl.lines.Line2D([0], [0], marker='o', color='w', markerfacecolor=color, markersize=6, label=f"comp {c}"))
    return colors, handles


def edge_widths(edges: List[Tuple[int, int, float]], wmin: float, wmax: float, scale: float) -> List[float]:
    widths: List[float] = []
    for _, _, w in edges:
        try:
            s = math.sqrt(max(0.0, w)) * scale
        except Exception:
            s = 1.0
        widths.append(min(wmax, max(wmin, s)))
    return widths


def main() -> None:
    args = parse_args()

    # Validate input paths early for clearer error messages
    if not os.path.isfile(args.nodes):
        sys.stderr.write(f"Nodes CSV not found: {args.nodes}\n")
        sys.exit(2)
    if not os.path.isfile(args.edges):
        sys.stderr.write(f"Edges CSV not found: {args.edges}\n")
        sys.exit(2)

    node_ids, components = read_nodes(args.nodes)
    edges = read_edges(args.edges)

    snodes, scomps, sedges = sample_graph(node_ids, components, edges, args.max_nodes, args.max_edges, args.seed)

    G = build_graph(snodes, scomps, sedges)
    pos = compute_layout(G, args.layout, args.seed)

    node_colors, legend_handles = make_colors(snodes, scomps)
    ewidths = edge_widths(sedges, args.edge_min_width, args.edge_max_width, args.weight_scale)

    plt.figure(figsize=(args.width, args.height), dpi=args.dpi)
    plt.axis('off')

    nx.draw_networkx_edges(G, pos, alpha=args.edge_alpha, width=ewidths, edge_color="#444444")
    nx.draw_networkx_nodes(G, pos, node_size=args.node_size, node_color=node_colors, linewidths=0.0)

    if not args.no_labels and len(snodes) <= 200:
        nx.draw_networkx_labels(G, pos, font_size=6)

    # Optional edge weight labels
    if args.edge_labels and len(sedges) > 0:
        try:
            # Label the strongest edges first to reduce clutter
            top_edges = sorted(sedges, key=lambda e: e[2], reverse=True)[: max(0, args.edge_labels_max)]
            edge_labels = {(u, v): format(w, args.edge_labels_fmt) for (u, v, w) in top_edges}
            nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, font_size=6, rotate=False)
        except Exception as e:
            sys.stderr.write(f"Warning: failed to draw edge labels: {e}\n")

    if args.title:
        plt.title(args.title)

    if legend_handles and not args.no_legend:
        plt.legend(handles=legend_handles, loc='best', fontsize=6, frameon=False)

    out_dir = os.path.dirname(args.out)
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)
    plt.tight_layout(pad=0.05)
    plt.savefig(args.out, bbox_inches='tight')
    print(f"Saved figure: {args.out} (nodes drawn={len(snodes)}, edges drawn={len(sedges)})")


if __name__ == "__main__":
    main()
